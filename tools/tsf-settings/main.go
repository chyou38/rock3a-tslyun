package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"mime/multipart"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
)

const version = "1.0.0"

type session struct {
	Token   string    `json:"token"`
	Cookie  string    `json:"cookie"`
	User    string    `json:"user"`
	Created time.Time `json:"created"`
	Expires time.Time `json:"expires"`
	IP      string    `json:"ip"`
}

type loginReq struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

type loginResp struct {
	OK        bool   `json:"ok"`
	Token     string `json:"token,omitempty"`
	User      string `json:"user,omitempty"`
	ExpiresAt int64  `json:"expires_at,omitempty"`
	Msg       string `json:"msg,omitempty"`
}

type callReq struct {
	Path        string `json:"path"`
	Method      string `json:"method"`
	Body        string `json:"body,omitempty"`
	ContentType string `json:"content_type,omitempty"`
}

type server struct {
	upstream string
	ttl      time.Duration
	audit    *os.File
	mu       sync.Mutex
	sessions map[string]*session
	limiter  *limiter
	client   *http.Client
}

type limiter struct {
	mu    sync.Mutex
	rows  map[string][]time.Time
	limit int
	win   time.Duration
}

func newLimiter(limit int, win time.Duration) *limiter {
	return &limiter{rows: map[string][]time.Time{}, limit: limit, win: win}
}

func (l *limiter) allow(ip string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := time.Now()
	rows := l.rows[ip]
	keep := rows[:0]
	for _, t := range rows {
		if now.Sub(t) <= l.win {
			keep = append(keep, t)
		}
	}
	l.rows[ip] = keep
	return len(keep) < l.limit
}

func (l *limiter) fail(ip string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.rows[ip] = append(l.rows[ip], time.Now())
}

func (l *limiter) clear(ip string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	delete(l.rows, ip)
}

func randomToken(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return fmt.Sprintf("%d", time.Now().UnixNano())
	}
	return hex.EncodeToString(b)
}

func clientIP(r *http.Request) string {
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		if i := strings.IndexByte(xff, ','); i >= 0 {
			xff = xff[:i]
		}
		return strings.TrimSpace(xff)
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err == nil {
		return host
	}
	return r.RemoteAddr
}

func jsonReply(w http.ResponseWriter, code int, obj interface{}) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(obj)
}

func readJSON(r *http.Request, dst interface{}, max int64) error {
	r.Body = http.MaxBytesReader(nil, r.Body, max)
	dec := json.NewDecoder(r.Body)
	return dec.Decode(dst)
}

func (s *server) auditLine(format string, args ...interface{}) {
	if s.audit == nil {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	fmt.Fprintf(s.audit, "%s %s\n", time.Now().Format(time.RFC3339), fmt.Sprintf(format, args...))
}

func (s *server) validSession(r *http.Request) *session {
	auth := strings.TrimSpace(r.Header.Get("Authorization"))
	if !strings.HasPrefix(auth, "Bearer ") {
		return nil
	}
	tok := strings.TrimSpace(auth[7:])
	if tok == "" {
		return nil
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	sess := s.sessions[tok]
	if sess == nil {
		return nil
	}
	if time.Now().After(sess.Expires) {
		delete(s.sessions, tok)
		return nil
	}
	return sess
}

func (s *server) login(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		jsonReply(w, 405, loginResp{Msg: "method not allowed"})
		return
	}
	ip := clientIP(r)
	if !s.limiter.allow(ip) {
		s.auditLine("LOGIN-RATE ip=%s", ip)
		jsonReply(w, 429, loginResp{Msg: "尝试次数过多，请 5 分钟后再试"})
		return
	}
	var lr loginReq
	if err := readJSON(r, &lr, 16*1024); err != nil {
		jsonReply(w, 400, loginResp{Msg: "参数错误"})
		return
	}
	lr.Username = strings.TrimSpace(lr.Username)
	lr.Password = strings.TrimSpace(lr.Password)
	if lr.Username == "" || lr.Password == "" {
		jsonReply(w, 400, loginResp{Msg: "请填写管理员用户名和密码"})
		return
	}
	form := url.Values{}
	form.Set("u", lr.Username)
	form.Set("p", lr.Password)
	form.Set("next", "/")
	req, err := http.NewRequest(http.MethodPost, s.upstream+"/login", strings.NewReader(form.Encode()))
	if err != nil {
		jsonReply(w, 502, loginResp{Msg: "上游地址错误"})
		return
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("User-Agent", "TSLSentry-Settings/"+version)
	resp, err := s.client.Do(req)
	if err != nil {
		jsonReply(w, 503, loginResp{Msg: "盒子认证服务不可达"})
		return
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, io.LimitReader(resp.Body, 64*1024))
	if resp.StatusCode != 302 {
		s.limiter.fail(ip)
		s.auditLine("LOGIN-FAIL ip=%s user=%s status=%d", ip, lr.Username, resp.StatusCode)
		jsonReply(w, 401, loginResp{Msg: "管理员用户名或密码不对"})
		return
	}
	cookie := ""
	for _, c := range resp.Cookies() {
		if c.Name == "tsf_sess" {
			cookie = c.Value
			break
		}
	}
	if cookie == "" {
		s.limiter.fail(ip)
		jsonReply(w, 502, loginResp{Msg: "认证服务未返回会话"})
		return
	}
	token := randomToken(32)
	exp := time.Now().Add(s.ttl)
	s.mu.Lock()
	s.sessions[token] = &session{Token: token, Cookie: cookie, User: lr.Username, Created: time.Now(), Expires: exp, IP: ip}
	s.mu.Unlock()
	s.limiter.clear(ip)
	s.auditLine("LOGIN-OK ip=%s user=%s", ip, lr.Username)
	jsonReply(w, 200, loginResp{OK: true, Token: token, User: lr.Username, ExpiresAt: exp.Unix()})
}

func (s *server) logout(w http.ResponseWriter, r *http.Request) {
	sess := s.validSession(r)
	if sess != nil {
		s.mu.Lock()
		delete(s.sessions, sess.Token)
		s.mu.Unlock()
	}
	jsonReply(w, 200, map[string]interface{}{"ok": true})
}

func (s *server) me(w http.ResponseWriter, r *http.Request) {
	sess := s.validSession(r)
	if sess == nil {
		jsonReply(w, 401, map[string]interface{}{"ok": false, "msg": "管理员会话已失效"})
		return
	}
	jsonReply(w, 200, map[string]interface{}{"ok": true, "user": sess.User, "expires_at": sess.Expires.Unix()})
}

func (s *server) health(w http.ResponseWriter, r *http.Request) {
	jsonReply(w, 200, map[string]interface{}{"ok": true, "service": "tsf-settings", "version": version, "time": time.Now().Unix()})
}

func (s *server) allowed(path string) bool {
	if !strings.HasPrefix(path, "/api/") || strings.HasPrefix(path, "/api/app/settings") {
		return false
	}
	if strings.Contains(path, "..") || strings.Contains(path, "://") {
		return false
	}
	blocked := []string{"/api/app/log", "/api/app/notifications", "/api/app/poll", "/api/app/ws", "/api/watch/alert"}
	for _, p := range blocked {
		if strings.HasPrefix(path, p) {
			return false
		}
	}
	return true
}

func (s *server) call(w http.ResponseWriter, r *http.Request) {
	sess := s.validSession(r)
	if sess == nil {
		jsonReply(w, 401, map[string]interface{}{"ok": false, "msg": "管理员会话已失效，请重新登录"})
		return
	}
	var cr callReq
	if err := readJSON(r, &cr, 2*1024*1024); err != nil {
		jsonReply(w, 400, map[string]interface{}{"ok": false, "msg": "请求参数错误"})
		return
	}
	cr.Path = strings.TrimSpace(cr.Path)
	if !s.allowed(cr.Path) {
		jsonReply(w, 403, map[string]interface{}{"ok": false, "msg": "该接口不在设置网关白名单内"})
		return
	}
	method := strings.ToUpper(strings.TrimSpace(cr.Method))
	if method == "" {
		method = http.MethodGet
	}
	if method != http.MethodGet && method != http.MethodPost && method != http.MethodDelete {
		jsonReply(w, 405, map[string]interface{}{"ok": false, "msg": "不支持的请求方法"})
		return
	}
	var body io.Reader
	if cr.Body != "" && method != http.MethodGet {
		body = bytes.NewReader([]byte(cr.Body))
	}
	req, err := http.NewRequest(method, s.upstream+cr.Path, body)
	if err != nil {
		jsonReply(w, 400, map[string]interface{}{"ok": false, "msg": "非法路径"})
		return
	}
	req.Header.Set("Cookie", "tsf_sess="+sess.Cookie)
	req.Header.Set("Accept", "application/json, */*")
	req.Header.Set("User-Agent", "TSLSentry-Settings/"+version)
	if cr.ContentType != "" {
		req.Header.Set("Content-Type", cr.ContentType)
	} else if body != nil {
		req.Header.Set("Content-Type", "application/json; charset=utf-8")
	}
	resp, err := s.client.Do(req)
	if err != nil {
		s.auditLine("CALL-ERR ip=%s user=%s %s %s err=%v", clientIP(r), sess.User, method, cr.Path, err)
		jsonReply(w, 502, map[string]interface{}{"ok": false, "msg": "盒子设置服务不可达"})
		return
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, 8*1024*1024))
	if err != nil {
		jsonReply(w, 502, map[string]interface{}{"ok": false, "msg": "读取设置响应失败"})
		return
	}
	ct := resp.Header.Get("Content-Type")
	if ct == "" {
		ct = "application/json; charset=utf-8"
	}
	s.auditLine("CALL ip=%s user=%s %s %s -> %d", clientIP(r), sess.User, method, cr.Path, resp.StatusCode)
	w.Header().Set("Content-Type", ct)
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(resp.StatusCode)
	_, _ = w.Write(data)
}

func (s *server) upload(w http.ResponseWriter, r *http.Request) {
	sess := s.validSession(r)
	if sess == nil {
		jsonReply(w, 401, map[string]interface{}{"ok": false, "msg": "管理员会话已失效，请重新登录"})
		return
	}
	if r.Method != http.MethodPost {
		jsonReply(w, 405, map[string]interface{}{"ok": false, "msg": "method not allowed"})
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 64*1024*1024)
	if err := r.ParseMultipartForm(64 * 1024 * 1024); err != nil {
		jsonReply(w, 413, map[string]interface{}{"ok": false, "msg": "文件超过 64MB 上限"})
		return
	}
	target := strings.TrimSpace(r.FormValue("path"))
	if !s.allowed(target) {
		jsonReply(w, 403, map[string]interface{}{"ok": false, "msg": "该上传接口不在设置网关白名单内"})
		return
	}
	file, hdr, err := r.FormFile("file")
	if err != nil {
		jsonReply(w, 400, map[string]interface{}{"ok": false, "msg": "缺少文件字段"})
		return
	}
	defer file.Close()
	extra := map[string]string{}
	rawExtra := strings.TrimSpace(r.FormValue("extra"))
	if rawExtra != "" {
		_ = json.Unmarshal([]byte(rawExtra), &extra)
	}
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	for k, v := range extra {
		if len(k) > 64 || strings.ContainsAny(k, "\r\n") {
			continue
		}
		_ = mw.WriteField(k, v)
	}
	fw, err := mw.CreateFormFile("file", hdr.Filename)
	if err != nil {
		jsonReply(w, 500, map[string]interface{}{"ok": false, "msg": "构造上传请求失败"})
		return
	}
	if _, err := io.Copy(fw, io.LimitReader(file, 64*1024*1024)); err != nil {
		jsonReply(w, 500, map[string]interface{}{"ok": false, "msg": "读取上传文件失败"})
		return
	}
	_ = mw.Close()
	req, err := http.NewRequest(http.MethodPost, s.upstream+target, &buf)
	if err != nil {
		jsonReply(w, 400, map[string]interface{}{"ok": false, "msg": "非法路径"})
		return
	}
	req.Header.Set("Cookie", "tsf_sess="+sess.Cookie)
	req.Header.Set("Content-Type", mw.FormDataContentType())
	req.Header.Set("Accept", "application/json, */*")
	req.Header.Set("User-Agent", "TSLSentry-Settings/"+version)
	resp, err := s.client.Do(req)
	if err != nil {
		s.auditLine("UPLOAD-ERR ip=%s user=%s %s err=%v", clientIP(r), sess.User, target, err)
		jsonReply(w, 502, map[string]interface{}{"ok": false, "msg": "盒子上传服务不可达"})
		return
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, 8*1024*1024))
	if err != nil {
		jsonReply(w, 502, map[string]interface{}{"ok": false, "msg": "读取上传响应失败"})
		return
	}
	ct := resp.Header.Get("Content-Type")
	if ct == "" {
		ct = "application/json; charset=utf-8"
	}
	s.auditLine("UPLOAD ip=%s user=%s %s %s -> %d", clientIP(r), sess.User, hdr.Filename, target, resp.StatusCode)
	w.Header().Set("Content-Type", ct)
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(resp.StatusCode)
	_, _ = w.Write(data)
}

func main() {
	listen := flag.String("listen", env("TSF_SETTINGS_LISTEN", "127.0.0.1:8099"), "listen address")
	upstream := flag.String("upstream", env("TSF_UPSTREAM", "http://127.0.0.1:80"), "upstream web origin")
	state := flag.String("state", env("TSF_SETTINGS_STATE", "/opt/tesla-sentry/tsf-settings-state.json"), "state directory marker")
	auditPath := flag.String("audit", env("TSF_SETTINGS_AUDIT", "/opt/tesla-sentry/tsf-settings-audit.log"), "audit log")
	ttlHours := flag.Int("ttl-hours", 168, "session TTL hours")
	flag.Parse()

	var audit *os.File
	var err error
	if auditPath != nil && *auditPath != "" {
		_ = os.MkdirAll(filepath.Dir(*auditPath), 0755)
		audit, err = os.OpenFile(*auditPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
		if err != nil {
			log.Printf("audit log disabled: %v", err)
			audit = nil
		}
	}
	_ = state

	s := &server{
		upstream: strings.TrimRight(*upstream, "/"),
		ttl:      time.Duration(*ttlHours) * time.Hour,
		audit:    audit,
		sessions: map[string]*session{},
		limiter:  newLimiter(5, 5*time.Minute),
		client: &http.Client{
			Timeout: 30 * time.Second,
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/health", s.health)
	mux.HandleFunc("/api/app/settings/login", s.login)
	mux.HandleFunc("/api/app/settings/logout", s.logout)
	mux.HandleFunc("/api/app/settings/me", s.me)
	mux.HandleFunc("/api/app/settings/call", s.call)
	mux.HandleFunc("/api/app/settings/upload", s.upload)

	srv := &http.Server{
		Addr:              *listen,
		Handler:           mux,
		ReadHeaderTimeout: 8 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      45 * time.Second,
		IdleTimeout:       90 * time.Second,
	}
	go func() {
		log.Printf("tsf-settings %s listening on %s upstream=%s", version, *listen, s.upstream)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatal(err)
		}
	}()
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
	if audit != nil {
		_ = audit.Close()
	}
}

func env(k, def string) string {
	if v := strings.TrimSpace(os.Getenv(k)); v != "" {
		return v
	}
	return def
}
