// tsf-doctor: tslbox 只读体检工具。
//
// 设计边界：
//   - 只读：不写业务文件、不重启服务、不改配置；
//   - 独立：通过 systemctl / /proc / 本地 HTTP 做旁路检查；
//   - 低风险：单项失败只记录在报告里，不阻塞主服务。
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"
)

const doctorVersion = "0.1.0"

type Check struct {
	ID     string `json:"id"`
	Group  string `json:"group"`
	Title  string `json:"title"`
	Level  string `json:"level"` // pass / warn / fail / info
	Detail string `json:"detail"`
	Value  any    `json:"value,omitempty"`
}

type Summary struct {
	Pass int `json:"pass"`
	Warn int `json:"warn"`
	Fail int `json:"fail"`
	Info int `json:"info"`
}

type Report struct {
	OK         bool    `json:"ok"`
	Status     string  `json:"status"`
	Tool       string  `json:"tool"`
	Version    string  `json:"version"`
	At         string  `json:"at"`
	DurationMS int64   `json:"ms"`
	Checks     []Check `json:"checks"`
	Summary    Summary `json:"summary"`
}

var (
	baseURL    = flag.String("base", "http://127.0.0.1", "本地服务地址")
	archive    = flag.String("archive", envDefault("TSF_ARCHIVE", "/mnt/tsf-storage/tsf-data/archive"), "归档区目录")
	user       = flag.String("user", os.Getenv("TSF_DOCTOR_USER"), "HTTP Basic 用户名")
	pass       = flag.String("pass", os.Getenv("TSF_DOCTOR_PASS"), "HTTP Basic 密码")
	cookie     = os.Getenv("TSF_DOCTOR_COOKIE")
	timeout    = flag.Duration("timeout", 8*time.Second, "单次请求超时")
	pretty     = flag.Bool("pretty", false, "格式化输出 JSON")
	showVer    = flag.Bool("version", false, "输出版本号")
	httpClient *http.Client
)

func envDefault(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func main() {
	flag.Parse()
	if *showVer {
		fmt.Println(doctorVersion)
		return
	}
	httpClient = &http.Client{Timeout: *timeout}
	start := time.Now()
	r := &Report{
		Tool:    "tsf-doctor",
		Version: doctorVersion,
		At:      time.Now().Format("2006-01-02 15:04:05"),
		Checks:  make([]Check, 0, 32),
	}
	checkServices(r)
	checkMemory(r)
	checkLoad(r)
	checkProcesses(r)
	checkDisks(r)
	checkArchive(r)
	checkHealthLog(r)
	mediaURL := checkAPIs(r)
	checkMedia(r, mediaURL)
	r.DurationMS = time.Since(start).Milliseconds()
	for _, c := range r.Checks {
		switch c.Level {
		case "pass":
			r.Summary.Pass++
		case "warn":
			r.Summary.Warn++
		case "fail":
			r.Summary.Fail++
		default:
			r.Summary.Info++
		}
	}
	r.OK = r.Summary.Fail == 0
	switch {
	case r.Summary.Fail > 0:
		r.Status = "fail"
	case r.Summary.Warn > 0:
		r.Status = "warn"
	default:
		r.Status = "pass"
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)
	if *pretty {
		enc.SetIndent("", "  ")
	}
	if err := enc.Encode(r); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
}

func (r *Report) add(id, group, title, level, detail string, value any) {
	r.Checks = append(r.Checks, Check{
		ID: id, Group: group, Title: title, Level: level, Detail: detail, Value: value,
	})
}

func checkServices(r *Report) {
	for _, svc := range []struct {
		id, group, title, unit string
	}{
		{"service.sentry", "system", "哨兵服务", "sentry-viewer"},
		{"service.live", "system", "同步服务", "tesla-live"},
	} {
		out, err := exec.Command("systemctl", "is-active", svc.unit).CombinedOutput()
		state := strings.TrimSpace(string(out))
		if state == "" {
			state = "unknown"
		}
		if err != nil || state != "active" {
			r.add(svc.id, svc.group, svc.title, "fail", "systemctl is-active="+state, state)
			continue
		}
		r.add(svc.id, svc.group, svc.title, "pass", "active", state)
	}
}

func checkMemory(r *Report) {
	vals := readMeminfo()
	totalKB := vals["MemTotal"]
	availKB := vals["MemAvailable"]
	if totalKB <= 0 || availKB <= 0 {
		r.add("system.memory", "system", "内存", "warn", "无法读取 /proc/meminfo", nil)
		return
	}
	level := "pass"
	detail := fmt.Sprintf("可用 %s / 总 %s", humanBytes(float64(availKB)*1024), humanBytes(float64(totalKB)*1024))
	if availKB < 80*1024 {
		level = "fail"
		detail += "，可用内存严重不足"
	} else if availKB < 150*1024 {
		level = "warn"
		detail += "，可用内存低于 150MB"
	}
	r.add("system.memory", "system", "内存", level, detail, map[string]any{
		"available_mb": availKB / 1024, "total_mb": totalKB / 1024,
	})
}

func checkLoad(r *Report) {
	data, err := os.ReadFile("/proc/loadavg")
	if err != nil {
		r.add("system.load", "system", "系统负载", "warn", "无法读取 /proc/loadavg", nil)
		return
	}
	fields := strings.Fields(string(data))
	if len(fields) < 3 {
		r.add("system.load", "system", "系统负载", "warn", "loadavg 格式异常", string(data))
		return
	}
	l1, _ := strconv.ParseFloat(fields[0], 64)
	l5, _ := strconv.ParseFloat(fields[1], 64)
	l15, _ := strconv.ParseFloat(fields[2], 64)
	ncpu := runtime.NumCPU()
	level := "pass"
	if l1 > float64(ncpu)*3 {
		level = "fail"
	} else if l1 > float64(ncpu)*1.5 {
		level = "warn"
	}
	r.add("system.load", "system", "系统负载", level,
		fmt.Sprintf("load %.2f / %.2f / %.2f，%d 核", l1, l5, l15, ncpu),
		map[string]any{"load1": l1, "load5": l5, "load15": l15, "cpu": ncpu})
}

func checkProcesses(r *Report) {
	viewerPID, viewerRSS := findProcess("sentry-viewer.py")
	syncPID, syncRSS := findProcess("tesla-live-sync.py")
	ffmpeg := countProcess("ffmpeg")
	level := "pass"
	parts := []string{}
	if viewerPID > 0 {
		parts = append(parts, fmt.Sprintf("viewer PID %d / RSS %s", viewerPID, humanBytes(float64(viewerRSS)*1024)))
	} else {
		level = "fail"
		parts = append(parts, "viewer 未找到")
	}
	if syncPID > 0 {
		parts = append(parts, fmt.Sprintf("sync PID %d / RSS %s", syncPID, humanBytes(float64(syncRSS)*1024)))
	} else {
		level = "fail"
		parts = append(parts, "sync 未找到")
	}
	parts = append(parts, fmt.Sprintf("ffmpeg %d 个", ffmpeg))
	r.add("system.processes", "system", "服务进程", level, strings.Join(parts, "；"),
		map[string]any{"viewer_pid": viewerPID, "viewer_rss_kb": viewerRSS,
			"sync_pid": syncPID, "sync_rss_kb": syncRSS, "ffmpeg": ffmpeg})
}

func checkDisks(r *Report) {
	checkDisk(r, "system.disk.root", "system", "系统盘", "/")
	checkDisk(r, "system.disk.storage", "system", "存储盘", "/mnt/tsf-storage")
}

func checkDisk(r *Report, id, group, title, path string) {
	var st syscall.Statfs_t
	if err := syscall.Statfs(path, &st); err != nil {
		r.add(id, group, title, "warn", "无法读取 "+path+"："+err.Error(), nil)
		return
	}
	total := float64(st.Blocks) * float64(st.Bsize)
	avail := float64(st.Bavail) * float64(st.Bsize)
	pct := 0.0
	if total > 0 {
		pct = avail / total * 100
	}
	level := "pass"
	if avail < 1<<30 || pct < 5 {
		level = "fail"
	} else if avail < 3<<30 || pct < 10 {
		level = "warn"
	}
	r.add(id, group, title, level,
		fmt.Sprintf("剩余 %s / 总 %s（%.1f%% 可用）", humanBytes(avail), humanBytes(total), pct),
		map[string]any{"path": path, "avail": int64(avail), "total": int64(total), "pct": pct})
}

func checkArchive(r *Report) {
	if *archive == "" {
		r.add("archive.files", "archive", "归档文件", "warn", "归档目录未配置", nil)
		return
	}
	info, err := os.Stat(*archive)
	if err != nil || !info.IsDir() {
		r.add("archive.files", "archive", "归档文件", "warn", "归档目录不可用："+*archive, nil)
		return
	}
	cats, err := os.ReadDir(*archive)
	if err != nil {
		r.add("archive.files", "archive", "归档文件", "warn", "读取归档目录失败："+err.Error(), nil)
		return
	}
	catN, eventN, partN, prunedN := 0, 0, 0, 0
	for _, cat := range cats {
		if !cat.IsDir() {
			continue
		}
		catN++
		evs, err := os.ReadDir(filepath.Join(*archive, cat.Name()))
		if err != nil {
			continue
		}
		for _, ev := range evs {
			if !ev.IsDir() {
				continue
			}
			eventN++
			files, err := os.ReadDir(filepath.Join(*archive, cat.Name(), ev.Name()))
			if err != nil {
				continue
			}
			for _, f := range files {
				if f.IsDir() {
					continue
				}
				switch {
				case strings.HasSuffix(f.Name(), ".part"):
					partN++
				case f.Name() == ".pruned":
					prunedN++
				}
			}
		}
	}
	level := "pass"
	if partN > 0 {
		level = "warn"
	}
	detail := fmt.Sprintf("%d 个分类 / %d 个事件；.part %d；.pruned %d", catN, eventN, partN, prunedN)
	if partN > 0 {
		detail += "（存在未完成临时文件）"
	}
	r.add("archive.files", "archive", "归档文件", level, detail,
		map[string]any{"categories": catN, "events": eventN, "part": partN, "pruned": prunedN})
}

func checkHealthLog(r *Report) {
	const fp = "/opt/tesla-sentry/health.log"
	data, err := os.ReadFile(fp)
	if err != nil {
		r.add("system.healthlog", "system", "健康日志", "warn", "无法读取 "+fp, nil)
		return
	}
	lines := strings.Split(string(data), "\n")
	if len(lines) > 120 {
		lines = lines[len(lines)-120:]
	}
	last := ""
	failLine, warnLine := "", ""
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		last = line
		low := strings.ToLower(line)
		if strings.Contains(low, "oom") || strings.Contains(low, "panic") || strings.Contains(low, "lockup") {
			failLine = line
		} else if warnLine == "" && (strings.Contains(low, "reset") ||
			strings.Contains(low, "failed") || strings.Contains(low, "degraded") ||
			strings.Contains(low, "error")) {
			warnLine = line
		}
	}
	level, detail := "pass", "末行："+truncate(last, 180)
	if failLine != "" {
		level, detail = "fail", "最近异常："+truncate(failLine, 180)
	} else if warnLine != "" {
		level, detail = "warn", "最近注意："+truncate(warnLine, 180)
	}
	if last == "" {
		level, detail = "warn", "健康日志为空"
	}
	r.add("system.healthlog", "system", "健康日志", level, detail, nil)
}

func checkAPIs(r *Report) string {
	mediaURL := ""

	code, _, body, err := fetch("GET", "/api/ver", nil)
	if err != nil {
		r.add("api.ver", "api", "版本接口", "fail", err.Error(), nil)
	} else if code != 200 {
		r.add("api.ver", "api", "版本接口", "fail", fmt.Sprintf("HTTP %d", code), code)
	} else {
		var m map[string]any
		_ = json.Unmarshal(body, &m)
		v, _ := m["v"].(string)
		r.add("api.ver", "api", "版本接口", "pass", "v="+v, v)
	}

	code, _, body, err = fetch("GET", "/api/live", nil)
	if err != nil {
		r.add("api.live", "api", "同步状态", "fail", err.Error(), nil)
	} else if code != 200 {
		r.add("api.live", "api", "同步状态", "fail", fmt.Sprintf("HTTP %d", code), code)
	} else {
		var m map[string]any
		_ = json.Unmarshal(body, &m)
		running, _ := m["running"].(bool)
		pending, _ := m["pending"].(float64)
		ago, _ := m["ago"].(float64)
		level, detail := "pass", fmt.Sprintf("running=%v pending=%d ago=%ds", running, int(pending), int(ago))
		if !running {
			level, detail = "fail", "同步线程未运行"
		} else if pending > 0 {
			level, detail = "warn", fmt.Sprintf("待同步 %d 项（ago=%ds）", int(pending), int(ago))
		} else if ago > 3600 {
			level, detail = "warn", fmt.Sprintf("最近同步 %d 分钟前", int(ago)/60)
		}
		r.add("api.live", "api", "同步状态", level, detail, m)
	}

	code, _, body, err = fetch("GET", "/api/storage/status", nil)
	if err != nil {
		r.add("api.storage", "api", "存储状态", "fail", err.Error(), nil)
	} else if code != 200 {
		r.add("api.storage", "api", "存储状态", "fail", fmt.Sprintf("HTTP %d", code), code)
	} else {
		var m map[string]any
		_ = json.Unmarshal(body, &m)
		ready, _ := m["storage_ready"].(bool)
		lun, _ := m["lun_backed"].(bool)
		state := fmt.Sprint(m["state"])
		source := fmt.Sprint(m["source"])
		level, detail := "pass", "ready=true source="+source+" state="+state
		if !ready {
			level, detail = "fail", "storage_ready=false"
		} else if !lun {
			level, detail = "warn", "LUN 未挂载镜像"
		}
		r.add("api.storage", "api", "存储状态", level, detail, m)
	}

	mediaURL = checkEvents(r)

	code, _, body, err = fetch("GET", "/api/events_meta", nil)
	if err != nil {
		r.add("api.events_meta", "api", "事件签名", "fail", err.Error(), nil)
	} else if code != 200 {
		r.add("api.events_meta", "api", "事件签名", "fail", fmt.Sprintf("HTTP %d", code), code)
	} else {
		var m map[string]any
		_ = json.Unmarshal(body, &m)
		sig, _ := m["sig"].(string)
		r.add("api.events_meta", "api", "事件签名", "pass", fmt.Sprintf("sig 长度 %d", len(sig)), len(sig))
	}

	code, _, _, err = fetch("GET", "/api/settings", nil)
	if err != nil {
		r.add("api.settings", "api", "设置接口", "fail", err.Error(), nil)
	} else if code != 200 {
		r.add("api.settings", "api", "设置接口", "fail", fmt.Sprintf("HTTP %d", code), code)
	} else {
		r.add("api.settings", "api", "设置接口", "pass", "可读取（不显示内容）", nil)
	}

	return mediaURL
}

func checkEvents(r *Report) string {
	code, _, body, err := fetch("GET", "/api/events", nil)
	if err != nil {
		r.add("api.events", "api", "事件列表", "fail", err.Error(), nil)
		return ""
	}
	if code != 200 {
		r.add("api.events", "api", "事件列表", "fail", fmt.Sprintf("HTTP %d", code), code)
		return ""
	}
	var top map[string]json.RawMessage
	if err := json.Unmarshal(body, &top); err != nil {
		r.add("api.events", "api", "事件列表", "fail", "JSON 解析失败："+err.Error(), nil)
		return ""
	}
	total, empty := 0, 0
	media := ""
	for _, raw := range top {
		var evs []struct {
			Name   string `json:"name"`
			Videos []struct {
				URL string `json:"url"`
			} `json:"videos"`
		}
		if err := json.Unmarshal(raw, &evs); err != nil {
			continue
		}
		for _, ev := range evs {
			total++
			if len(ev.Videos) == 0 {
				empty++
				continue
			}
			for _, v := range ev.Videos {
				if !strings.HasSuffix(v.URL, ".mp4") {
					continue
				}
				if media == "" {
					media = v.URL
				}
				if strings.Contains(v.URL, "-front.mp4") {
					media = v.URL
					break
				}
			}
		}
	}
	level, detail := "pass", fmt.Sprintf("%d 个事件，媒体样本 %s", total, media)
	if empty > 0 {
		level, detail = "warn", fmt.Sprintf("%d 个事件，空事件 %d 个", total, empty)
	}
	if media == "" {
		level, detail = "warn", fmt.Sprintf("%d 个事件，未找到 mp4 样本", total)
	}
	r.add("api.events", "api", "事件列表", level, detail,
		map[string]any{"events": total, "empty": empty})
	return media
}

func checkMedia(r *Report, mediaURL string) {
	if mediaURL == "" {
		r.add("media.head", "media", "媒体 HEAD", "warn", "没有可用事件，跳过", nil)
		r.add("media.range", "media", "媒体 Range", "warn", "没有可用事件，跳过", nil)
		r.add("media.thumb", "media", "缩略图", "warn", "没有可用事件，跳过", nil)
		return
	}
	code, hdr, _, err := fetch("HEAD", mediaURL, nil)
	if err != nil {
		r.add("media.head", "media", "媒体 HEAD", "fail", err.Error(), nil)
	} else if code != 200 {
		r.add("media.head", "media", "媒体 HEAD", "fail", fmt.Sprintf("HTTP %d", code), code)
	} else {
		lengths := hdr.Values("Content-Length")
		level, detail := "pass", fmt.Sprintf("HTTP 200，%s，Content-Length %d 个", humanBytes(float64(parseInt64(first(lengths)))), len(lengths))
		if len(lengths) != 1 {
			level, detail = "fail", fmt.Sprintf("Content-Length 出现 %d 个（应为 1 个）", len(lengths))
		}
		if !strings.Contains(strings.ToLower(hdr.Get("Accept-Ranges")), "bytes") {
			if level == "pass" {
				level = "warn"
			}
			detail += "，Accept-Ranges 缺失"
		}
		r.add("media.head", "media", "媒体 HEAD", level, detail, nil)
	}

	code, hdr, body, err := fetch("GET", mediaURL, map[string]string{"Range": "bytes=0-99"})
	if err != nil {
		r.add("media.range", "media", "媒体 Range", "fail", err.Error(), nil)
	} else if code != 206 {
		r.add("media.range", "media", "媒体 Range", "fail", fmt.Sprintf("HTTP %d（应为 206）", code), code)
	} else {
		want := parseInt64(hdr.Get("Content-Length"))
		level, detail := "pass", fmt.Sprintf("HTTP 206，Content-Length %d，实际 %d 字节", want, len(body))
		if len(body) != 100 || (want > 0 && want != 100) {
			level, detail = "warn", fmt.Sprintf("HTTP 206，但期望 100 字节，实际 %d（Content-Length=%d）", len(body), want)
		}
		r.add("media.range", "media", "媒体 Range", level, detail, nil)
	}

	thumb := strings.Replace(mediaURL, "/media/", "/thumb/", 1)
	if thumb == mediaURL {
		r.add("media.thumb", "media", "缩略图", "warn", "媒体路径不含 /media/，跳过", nil)
		return
	}
	code, hdr, body, err = fetch("GET", thumb+"?t=1", nil)
	if err != nil {
		r.add("media.thumb", "media", "缩略图", "warn", err.Error(), nil)
		return
	}
	ctype := hdr.Get("Content-Type")
	if code == 200 && strings.HasPrefix(strings.ToLower(ctype), "image/") && len(body) > 0 {
		r.add("media.thumb", "media", "缩略图", "pass", fmt.Sprintf("HTTP 200，%s，%s", ctype, humanBytes(float64(len(body)))), nil)
	} else if code == 404 {
		r.add("media.thumb", "media", "缩略图", "warn", "HTTP 404（缩略图未生成）", nil)
	} else {
		r.add("media.thumb", "media", "缩略图", "warn", fmt.Sprintf("HTTP %d，Content-Type=%s", code, ctype), nil)
	}
}

func fetch(method, path string, headers map[string]string) (int, http.Header, []byte, error) {
	url := strings.TrimRight(*baseURL, "/") + path
	req, err := http.NewRequest(method, url, nil)
	if err != nil {
		return 0, nil, nil, err
	}
	req.Header.Set("Cache-Control", "no-cache")
	req.Header.Set("User-Agent", "tsf-doctor/"+doctorVersion)
	if cookie != "" {
		req.Header.Set("Cookie", cookie)
	} else if *user != "" || *pass != "" {
		req.SetBasicAuth(*user, *pass)
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		return 0, nil, nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return resp.StatusCode, resp.Header, nil, err
	}
	return resp.StatusCode, resp.Header, body, nil
}

func readMeminfo() map[string]int64 {
	out := map[string]int64{}
	data, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		return out
	}
	for _, line := range strings.Split(string(data), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 || !strings.HasSuffix(fields[0], ":") {
			continue
		}
		n, _ := strconv.ParseInt(fields[1], 10, 64)
		out[strings.TrimSuffix(fields[0], ":")] = n
	}
	return out
}

func findProcess(name string) (int, int64) {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return 0, 0
	}
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		pid, err := strconv.Atoi(e.Name())
		if err != nil {
			continue
		}
		cmd, err := os.ReadFile(filepath.Join("/proc", e.Name(), "cmdline"))
		if err != nil || !strings.Contains(string(cmd), name) {
			continue
		}
		rss := procRSS(pid)
		return pid, rss
	}
	return 0, 0
}

func countProcess(name string) int {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return 0
	}
	n := 0
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		if _, err := strconv.Atoi(e.Name()); err != nil {
			continue
		}
		cmd, err := os.ReadFile(filepath.Join("/proc", e.Name(), "cmdline"))
		if err == nil && strings.Contains(string(cmd), name) {
			n++
		}
	}
	return n
}

func procRSS(pid int) int64 {
	data, err := os.ReadFile(filepath.Join("/proc", strconv.Itoa(pid), "status"))
	if err != nil {
		return 0
	}
	for _, line := range strings.Split(string(data), "\n") {
		if strings.HasPrefix(line, "VmRSS:") {
			fields := strings.Fields(line)
			if len(fields) >= 2 {
				n, _ := strconv.ParseInt(fields[1], 10, 64)
				return n
			}
		}
	}
	return 0
}

func humanBytes(n float64) string {
	const unit = 1024.0
	if n < unit {
		return fmt.Sprintf("%.0fB", n)
	}
	units := []string{"KB", "MB", "GB", "TB"}
	v := n
	i := -1
	for v >= unit && i < len(units)-1 {
		v /= unit
		i++
	}
	if i < 0 {
		i = 0
	}
	return fmt.Sprintf("%.1f%s", v, units[i])
}

func parseInt64(s string) int64 {
	n, _ := strconv.ParseInt(strings.TrimSpace(s), 10, 64)
	return n
}

func first(v []string) string {
	if len(v) == 0 {
		return ""
	}
	return v[0]
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}
