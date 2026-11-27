// tsf-sysd: TeslaBox 只读系统状态缓存服务。
//
// 设计边界：
//   - 只读：不写业务文件、不重启其它服务、不改车机写入路径；
//   - 常驻：把 journalctl/dmesg/OTG/日志文件的热数据缓存起来，体检直接读内存；
//   - 可降级：sentry-viewer 连不上或未 ready 时，自动回退原有 Python 采集。
package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

const sysdVersion = "0.1.0"

const (
	mppReason  = "check buffer found NULL pointer from get_packet"
	waitReason = "wait task break by signal"
)

var (
	hbRe   = regexp.MustCompile(`hb mem=(\d+)M cma=(\d+)M load=([^ ]+) temp=(\d+)C usb=(.*?) lun=([^ ]+) reset=(\d+) null=(\d+)`)
	evRe   = regexp.MustCompile(`usb state:|LUN |usb reset|mpp buffer|ALERT|service .*NOT active|kernel OOM`)
	mppRe  = regexp.MustCompile(`check buffer found NULL pointer`)
	waitRe = regexp.MustCompile(`wait task break by signal`)
	kernRe = regexp.MustCompile(`dwc3.*(device reset|device disconnect|device connect)|rkvdec|rk_vcodec|mpp_wait|check buffer`)
	errRe  = regexp.MustCompile(`Traceback|Exception|failed|mpp_buffer: check buffer`)
	// journalctl 只送关心的行，避免 follower 把 sentry-viewer 的全部 mpp_info 都读进来。
	journalGrep = "mpp_buffer|Traceback|Exception|failed"
)

type HB struct {
	MemMB      int    `json:"mem_mb"`
	CMAMB      int    `json:"cma_mb"`
	Load       string `json:"load"`
	TempC      int    `json:"temp_c"`
	USB        string `json:"usb"`
	LUN        string `json:"lun"`
	ResetTotal int    `json:"reset_total"`
	NullTotal  int    `json:"null_total"`
}

type OTG struct {
	State           string   `json:"state"`
	Connected       bool     `json:"connected"`
	Speed           string   `json:"speed"`
	MaxSpeed        string   `json:"max_speed"`
	Kind            string   `json:"kind"`
	LUN             string   `json:"lun"`
	LUNBacked       bool     `json:"lun_backed"`
	WatchResetTotal int      `json:"watch_reset_total"`
	WatchNullTotal  int      `json:"watch_null_total"`
	Events          []string `json:"events"`
}

type Decode struct {
	MPPNullTotal    int      `json:"mpp_null_total"`
	MPPNullWindow   int      `json:"mpp_null_window"`
	MPPNullReason   string   `json:"mpp_null_reason"`
	MPPNullEvents   []string `json:"mpp_null_events"`
	WaitBreakTotal  int      `json:"wait_break_total"`
	WaitBreakReason string   `json:"wait_break_reason"`
	WaitBreakEvents []string `json:"wait_break_events"`
	JournalErrors   []string `json:"journal_errors"`
}

type Status struct {
	Ready       bool     `json:"ready"`
	Source      string   `json:"source"`
	Version     string   `json:"version"`
	CollectedAt string   `json:"collected_at"`
	OTG         OTG      `json:"otg"`
	Decode      Decode   `json:"decode"`
	Gadget      []string `json:"gadget"`
	Sync        []string `json:"sync"`
	Health      []string `json:"health"`
	Kernel      []string `json:"kernel"`
	HB          HB       `json:"hb"`
}

type collector struct {
	mu          sync.RWMutex
	st          Status
	logDir      string
	journalUnit string
	interval    time.Duration
	jerrors     []string
	watchLoaded bool
	watchEvents []string
}

func NewCollector(logDir, unit string, interval time.Duration) *collector {
	return &collector{
		logDir:      logDir,
		journalUnit: unit,
		interval:    interval,
		st: Status{
			Ready:   false,
			Source:  "tsf-sysd",
			Version: sysdVersion,
			OTG:     OTG{Events: []string{}},
			Decode:  Decode{MPPNullWindow: 8000, MPPNullReason: mppReason, WaitBreakReason: waitReason},
			Gadget:  []string{}, Sync: []string{}, Health: []string{}, Kernel: []string{},
			HB: HB{},
		},
	}
}

func tailLines(path string, max int, maxBytes int64) []string {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return nil
	}
	start := st.Size() - maxBytes
	if start < 0 {
		start = 0
	}
	if _, err := f.Seek(start, io.SeekStart); err != nil {
		return nil
	}
	raw, err := io.ReadAll(f)
	if err != nil {
		return nil
	}
	lines := strings.Split(strings.ReplaceAll(string(raw), "\x00", ""), "\n")
	if len(lines) > max {
		lines = lines[len(lines)-max:]
	}
	out := make([]string, 0, len(lines))
	for _, ln := range lines {
		ln = strings.TrimSpace(ln)
		if ln != "" {
			out = append(out, ln)
		}
	}
	return out
}

func pick(lines []string, limit int) []string {
	out := make([]string, 0, limit)
	for _, ln := range lines {
		ln = strings.TrimSpace(ln)
		if ln == "" || !evRe.MatchString(ln) {
			continue
		}
		if len(ln) > 240 {
			ln = ln[:240]
		}
		out = append(out, ln)
	}
	if len(out) > limit {
		out = out[len(out)-limit:]
	}
	return out
}

func lastHB(lines []string) HB {
	for i := len(lines) - 1; i >= 0; i-- {
		m := hbRe.FindStringSubmatch(lines[i])
		if len(m) != 9 {
			continue
		}
		v := func(s string) int { n, _ := strconv.Atoi(s); return n }
		return HB{
			MemMB: v(m[1]), CMAMB: v(m[2]), Load: m[3], TempC: v(m[4]),
			USB: m[5], LUN: m[6], ResetTotal: v(m[7]), NullTotal: v(m[8]),
		}
	}
	return HB{}
}

func readOne(path string) string {
	b, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(strings.ReplaceAll(string(b), "\x00", ""))
}

func firstUDC() string {
	ents, err := os.ReadDir("/sys/class/udc")
	if err != nil || len(ents) == 0 {
		return ""
	}
	return ents[0].Name()
}

func speedText(code string) string {
	switch strings.ToLower(strings.TrimSpace(code)) {
	case "":
		return ""
	case "low":
		return "USB 1.0 · 1.5Mbps"
	case "full":
		return "USB 1.1 · 12Mbps"
	case "high":
		return "USB 2.0 · 480Mbps"
	case "super", "super-speed":
		return "USB 3.0 · 5Gbps"
	case "super-speed-plus", "super+":
		return "USB 3.2 · 10Gbps"
	case "unknown":
		return ""
	default:
		return code
	}
}

func (c *collector) otgNow() OTG {
	udc := firstUDC()
	state, speed, maxSpeed := "", "", ""
	if udc != "" {
		state = readOne("/sys/class/udc/" + udc + "/state")
		speed = readOne("/sys/class/udc/" + udc + "/current_speed")
		maxSpeed = readOne("/sys/class/udc/" + udc + "/maximum_speed")
	}
	connected := udc != "" &&
		(state == "configured" || state == "addressed" || state == "suspended") &&
		strings.ToLower(speed) != "unknown"
	lunFile := ""
	fns, _ := filepath.Glob("/sys/kernel/config/usb_gadget/g1/functions/mass_storage*/lun.0/file")
	if len(fns) > 0 {
		lunFile = readOne(fns[0])
	}
	lunName := filepath.Base(lunFile)
	kind := "none"
	if udc != "" {
		if !connected {
			kind = "off"
		} else if lunFile != "" {
			kind = "ready"
		} else {
			kind = "ejected"
		}
	}
	return OTG{
		State: state, Connected: connected, Speed: speedText(speed), MaxSpeed: speedText(maxSpeed),
		Kind: kind, LUN: lunName, LUNBacked: lunFile != "",
	}
}

func (c *collector) collectFiles() ([]string, []string, []string, []string, HB) {
	// watch.log 只在启动时读一次全量，之后只读末尾 32KB；OTG 事件在内存里合并去重。
	watchPath := filepath.Join(c.logDir, "watch.log")
	var watch []string
	if !c.watchLoaded {
		watch = tailLines(watchPath, 14000, 2*1024*1024)
		c.watchLoaded = true
	} else {
		watch = tailLines(watchPath, 1200, 32*1024)
	}
	gadget := tailLines(filepath.Join(c.logDir, "tesla-gadget.log"), 20, 16*1024)
	sync := tailLines(filepath.Join(c.logDir, "tesla-sync.log"), 20, 16*1024)
	health := tailLines(filepath.Join(c.logDir, "health.log"), 8, 16*1024)
	hb := lastHB(watch)
	events := mergeEvents(c.watchEvents, pick(watch, 12), 12)
	c.watchEvents = events
	last := func(lines []string, n int) []string {
		if len(lines) > n {
			lines = lines[len(lines)-n:]
		}
		return lines
	}
	return events, last(gadget, 8), last(sync, 6), last(health, 6), hb
}

func mergeEvents(old, add []string, max int) []string {
	out := append([]string(nil), old...)
	seen := make(map[string]bool, len(out)+len(add))
	for _, s := range out {
		seen[s] = true
	}
	for _, s := range add {
		if s == "" || seen[s] {
			continue
		}
		seen[s] = true
		out = append(out, s)
	}
	if len(out) > max {
		out = out[len(out)-max:]
	}
	return out
}

func (c *collector) updateDmesg() {
	out, err := exec.Command("dmesg").Output()
	if err != nil {
		return
	}
	lines := strings.Split(strings.ReplaceAll(string(out), "\x00", ""), "\n")
	kernel := make([]string, 0, 10)
	wait := 0
	for _, ln := range lines {
		ln = strings.TrimSpace(ln)
		if ln == "" {
			continue
		}
		if waitRe.MatchString(ln) {
			wait++
		}
		if kernRe.MatchString(ln) {
			if len(ln) > 240 {
				ln = ln[:240]
			}
			kernel = append(kernel, ln)
			if len(kernel) > 10 {
				kernel = kernel[len(kernel)-10:]
			}
		}
	}
	c.mu.Lock()
	c.st.Kernel = kernel
	c.st.Decode.WaitBreakTotal = wait
	// 从 dmesg 里取最后 4 条 wait 中断，作为原因样本
	waitEvents := make([]string, 0, 4)
	for _, ln := range lines {
		ln = strings.TrimSpace(ln)
		if ln != "" && waitRe.MatchString(ln) {
			if len(ln) > 240 {
				ln = ln[:240]
			}
			waitEvents = append(waitEvents, ln)
			if len(waitEvents) > 4 {
				waitEvents = waitEvents[len(waitEvents)-4:]
			}
		}
	}
	c.st.Decode.WaitBreakEvents = waitEvents
	c.mu.Unlock()
}

func (c *collector) collectOnce() {
	events, gadget, sync, health, hb := c.collectFiles()
	otg := c.otgNow()
	c.mu.Lock()
	otg.WatchResetTotal = hb.ResetTotal
	otg.WatchNullTotal = hb.NullTotal
	otg.Events = events
	c.st.OTG = otg
	c.st.Gadget = gadget
	c.st.Sync = sync
	c.st.Health = health
	c.st.HB = hb
	c.st.CollectedAt = time.Now().Format("2006-01-02 15:04:05")
	c.mu.Unlock()
}

func (c *collector) addMPP(line string) {
	line = strings.TrimSpace(line)
	if len(line) > 240 {
		line = line[:240]
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	c.st.Decode.MPPNullTotal++
	ev := append(c.st.Decode.MPPNullEvents, line)
	if len(ev) > 6 {
		ev = ev[len(ev)-6:]
	}
	c.st.Decode.MPPNullEvents = ev
}

func (c *collector) addError(line string) {
	line = strings.TrimSpace(line)
	if len(line) > 240 {
		line = line[:240]
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	c.jerrors = append(c.jerrors, line)
	if len(c.jerrors) > 5 {
		c.jerrors = c.jerrors[len(c.jerrors)-5:]
	}
	c.st.Decode.JournalErrors = append([]string(nil), c.jerrors...)
}

func (c *collector) journalSnapshot() {
	args := []string{"-b", "-u", c.journalUnit, "-q", "--no-pager", "-n", "8000"}
	out, err := exec.Command("journalctl", args...).Output()
	if err != nil {
		log.Printf("journal snapshot: %v", err)
		return
	}
	lines := strings.Split(strings.ReplaceAll(string(out), "\x00", ""), "\n")
	mpp := 0
	mppEvents := make([]string, 0, 6)
	errors := make([]string, 0, 5)
	for _, ln := range lines {
		ln = strings.TrimSpace(ln)
		if ln == "" {
			continue
		}
		if mppRe.MatchString(ln) {
			mpp++
			mppEvents = append(mppEvents, ln)
			if len(mppEvents) > 6 {
				mppEvents = mppEvents[len(mppEvents)-6:]
			}
		}
		if errRe.MatchString(ln) {
			errors = append(errors, ln)
			if len(errors) > 5 {
				errors = errors[len(errors)-5:]
			}
		}
	}
	c.mu.Lock()
	c.st.Decode.MPPNullTotal = mpp
	c.st.Decode.MPPNullEvents = mppEvents
	c.jerrors = errors
	c.st.Decode.JournalErrors = append([]string(nil), errors...)
	c.mu.Unlock()
}

func (c *collector) followJournal() {
	for {
		// 用 grep 在子进程侧过滤，避免 Go 读取 sentry-viewer 的全部 mpp_info。
		cmd := exec.Command("sh", "-c", "journalctl -b -u "+c.journalUnit+" -q --no-pager -n 0 -f | grep -E --line-buffered '"+journalGrep+"'")
		stdout, err := cmd.StdoutPipe()
		if err != nil {
			log.Printf("journal follow pipe: %v", err)
			time.Sleep(3 * time.Second)
			continue
		}
		cmd.Stderr = io.Discard
		if err := cmd.Start(); err != nil {
			log.Printf("journal follow start: %v", err)
			time.Sleep(3 * time.Second)
			continue
		}
		sc := bufio.NewScanner(stdout)
		sc.Buffer(make([]byte, 64*1024), 1024*1024)
		for sc.Scan() {
			ln := sc.Text()
			if mppRe.MatchString(ln) {
				c.addMPP(ln)
			}
			if errRe.MatchString(ln) {
				c.addError(ln)
			}
		}
		_ = cmd.Wait()
		time.Sleep(2 * time.Second)
	}
}

func (c *collector) run() {
	// 先做一次快照，再开始跟随；期间 ready=false，Python 会走原采集。
	c.journalSnapshot()
	c.collectOnce()
	c.updateDmesg()
	c.mu.Lock()
	c.st.Ready = true
	c.st.CollectedAt = time.Now().Format("2006-01-02 15:04:05")
	c.mu.Unlock()
	go c.followJournal()
	tick := time.NewTicker(c.interval)
	defer tick.Stop()
	dmesgTick := time.NewTicker(10 * time.Second)
	defer dmesgTick.Stop()
	for {
		select {
		case <-tick.C:
			c.collectOnce()
		case <-dmesgTick.C:
			c.updateDmesg()
		}
	}
}

func (c *collector) statusJSON() []byte {
	c.mu.RLock()
	st := c.st
	c.mu.RUnlock()
	st.OTG.Events = append([]string(nil), st.OTG.Events...)
	st.Decode.MPPNullEvents = append([]string(nil), st.Decode.MPPNullEvents...)
	st.Decode.WaitBreakEvents = append([]string(nil), st.Decode.WaitBreakEvents...)
	st.Decode.JournalErrors = append([]string(nil), st.Decode.JournalErrors...)
	st.Gadget = append([]string(nil), st.Gadget...)
	st.Sync = append([]string(nil), st.Sync...)
	st.Health = append([]string(nil), st.Health...)
	st.Kernel = append([]string(nil), st.Kernel...)
	b, _ := json.MarshalIndent(st, "", "  ")
	return b
}

func main() {
	listen := flag.String("listen", "127.0.0.1:8099", "监听地址（只建议回环）")
	logDir := flag.String("log-dir", "/opt/tesla-sentry", "watch/gadget/sync/health 日志目录")
	unit := flag.String("unit", "sentry-viewer.service", "用于解码错误统计的 systemd unit")
	interval := flag.Duration("interval", 2*time.Second, "文件/OTG 采样间隔")
	once := flag.Bool("once", false, "只采集一次并输出 JSON（测试用）")
	showVer := flag.Bool("version", false, "输出版本号")
	flag.Parse()
	if *showVer {
		fmt.Println(sysdVersion)
		return
	}
	c := NewCollector(*logDir, *unit, *interval)
	if *once {
		c.journalSnapshot()
		c.collectOnce()
		c.updateDmesg()
		c.mu.Lock()
		c.st.Ready = true
		c.mu.Unlock()
		os.Stdout.Write(c.statusJSON())
		return
	}
	go c.run()
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		_, _ = io.WriteString(w, "ok\n")
	})
	mux.HandleFunc("/status", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		b := c.statusJSON()
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.Header().Set("Cache-Control", "no-store")
		_, _ = w.Write(b)
	})
	srv := &http.Server{
		Addr:              *listen,
		Handler:           mux,
		ReadHeaderTimeout: 2 * time.Second,
	}
	log.Printf("tsf-sysd %s listening on %s", sysdVersion, *listen)
	if err := srv.ListenAndServe(); err != nil {
		log.Fatal(err)
	}
}
