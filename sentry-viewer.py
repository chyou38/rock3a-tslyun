#!/usr/bin/env python3
"""TSL 哨兵视频查看器 - 单文件, 纯标准库, 无依赖
功能: 多路播放器(4路/6路自适应) / 时间线 / 皮肤上传 / 锁车语音上传(经归档同步写入车机U盘)
访问: http://<rock3a-ip>/
"""
import base64
import datetime
import json
import os
import re
import hmac
import hashlib
import math
import shutil
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import socket
import select
import signal
import http.client
import ssl
import zipfile
import tempfile
import sys
import fcntl
import glob
try:
    import yaml
except ImportError:
    yaml = None
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---- 配置加载兜底 ----
# systemd 的 EnvironmentFile 会注入 conf; 为兼容手动启动 (无 EnvironmentFile),
# 在读取任何 TSF_* 之前, 把 conf 里尚未出现在环境变量中的项补进 os.environ。
# 优先级: 显式环境变量 > /etc/tesla-sentry.conf > 代码默认值; 空值按"用默认"处理。
def _load_conf(path="/etc/tesla-sentry.conf"):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k.startswith("TSF_") and v and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


_load_conf()

# 路径/端口优先取环境变量 (缺失时已由 _load_conf 从 conf 补齐), 便于改归档区、端口等
ARCHIVE = os.environ.get("TSF_ARCHIVE", "/archive")
SKIN_DIR = os.path.join(ARCHIVE, ".skins")
AUDIO_Q = os.path.join(ARCHIVE, "boombox-queue")
AUDIO_DONE = os.path.join(ARCHIVE, "boombox-done")
FILES_DIR = os.path.join(ARCHIVE, "files")
PORT = int(os.environ.get("TSF_PORT", "80"))
CATS = ["SentryClips", "SavedClips", "RecentClips"]
# ===== 多语言表 (由 tools/i18n_*.json 生成, key 为中文原文) =====
LANG_NAMES = [("zh", "中文"), ("en", "English"), ("de", "Deutsch"), ("fr", "Français"),
              ("it", "Italiano"), ("es", "Español"), ("nl", "Nederlands"), ("ru", "Русский"),
              ("ja", "日本語"), ("ko", "한국어")]
LANG_TABLE = {"de":{"品牌":"Marke","App ID — cli_ 开头":"App ID — beginnt mit cli_","App Secret (已保存则留空表示不修改)":"App Secret (leer lassen = unverändert)","‹ 返回":"‹ Zurück","⏳ 待写入车机U盘:":"⏳ Warten auf Schreiben auf den USB-Stick:","▶ 轻触开始同步播放":"▶ Tippen für synchrone Wiedergabe","⚙ 个性化":"⚙ Personalisieren","✅ 已写入:":"✅ Geschrieben:","上传 CSS 皮肤文件或背景图 (jpg/png/webp)。CSS 中引用图片请用 /skin-media/文件名。":"CSS-Skin-Datei oder Hintergrundbild hochladen (jpg/png/webp). Bilder im CSS über /skin-media/Dateiname einbinden.","下载":"Herunterladen","下载清晰度":"Download-Qualität","主题":"Design","也推手动保存":"Manuelle Speicherungen ebenfalls pushen","仅支持 wav/mp3":"Nur wav/mp3 unterstützt","仅限本人访问":"Nur für den Besitzer","今天":"Heute","位置":"Position","使用中":"Aktiv","侦测到物体移动":"Bewegung erkannt","侦测到碰撞/震动":"Aufprall/Erschütterung erkannt","保存失败":"Speichern fehlgeschlagen","保存设置":"Einstellungen speichern","修改密码":"Passwort ändern","全选":"Alle auswählen","全部":"Alle","全部日期":"Alle Daten","再输一次新密码":"Neues Passwort wiederholen","删除":"Löschen","刹车":"Bremse","刹车占比":"Bremsanteil","前视":"Vorne","升级会从 GitHub 及多个镜像并发竞速拉取最新程序, 覆盖本机文件并自动重启服务 (约5秒); 配置、录像、登录信息不受影响。":"Das Update lädt das neueste Programm von GitHub und mehreren Mirrors parallel, überschreibt lokale Dateien und startet den Dienst automatisch neu (ca. 5 s); Konfiguration, Aufnahmen und Anmeldedaten bleiben unberührt.","半透明单行: 时间/位置/车速/挡位/油门/刹车, 基本不挡画面":"Eine halbtransparente Zeile: Zeit/Position/Geschwindigkeit/Gang/Pedale/Bremse, verdeckt kaum","单选取原文件直接下载(加水印时走本机合成)；多选合成一个多画面视频。下载/打包按所选清晰度导出(首次需等转码)。":"Einzelauswahl lädt die Originaldatei direkt herunter (mit Wasserzeichen lokal komponiert); Mehrfachauswahl fügt ein Multi-View-Video zusammen. Download/ZIP-Export in der gewählten Qualität (beim ersten Mal Wartezeit durch Transkodierung).","原因":"Grund","原画":"Original","发送测试":"Test senden","叠加行车信息水印":"Fahrdaten-Wasserzeichen einblenden","右B柱":"B-Säule rechts","右前翼":"Kotflügel vorn rechts","右翼子板":"Kotflügel rechts","合成视频":"Video zusammenfügen","同步状态":"Sync-Status","后视":"Hinten","启用推送":"Push aktivieren","哨兵告警":"Sentry-Alarme","哨兵模式触发":"Sentry-Modus ausgelöst","哨兵触发时把时间/位置/触发原因和触发画面推到飞书。默认走自建应用私聊(只有你本人可见)；也可切到群机器人 webhook(群里都能看到)。视频推送只支持私聊。":"Bei Sentry-Auslösung werden Zeit/Position, Auslösegrund und Auslösebild an Feishu gepusht. Standardmäßig private Nachrichten über die eigene App (nur für dich sichtbar); alternativ Gruppen-Bot-webhook (für alle in der Gruppe sichtbar). Video-Push nur für private Nachrichten.","哨兵警觉":"Sentry-Wahrnehmung","回滚到上一版本":"Zur vorherigen Version zurückkehren","天":"Tage","实时同步中":"Live-Sync läuft","密码":"Passwort","尝试次数过多，请 5 分钟后再试":"Zu viele Versuche, bitte in 5 Minuten erneut versuchen","展开详细数据 ⌄":"Details ausklappen ⌄","左B柱":"B-Säule links","左前翼":"Kotflügel vorn links","左翼子板":"Kotflügel links","已保存":"Gespeichert","已删除":"Gelöscht","已加入队列, 归档同步时写入车机U盘":"In Warteschlange, wird bei der Archiv-Synchronisierung auf den Auto-USB-Stick geschrieben","已同步":"Synchronisiert","已是最新":"Aktuell","延迟推送":"Push-Verzögerung","当前密码":"Aktuelles Passwort","当前版本":"Aktuelle Version","恢复车机导出":"Auto-Zugriff wiederherstellen","手动保存":"Manuelle Speicherung","打包zip":"ZIP-Paket","按喇叭保存":"Hupen-Speicherung","换个日期或点「全部」查看本分类所有事件":"Anderes Datum wählen oder \"Alle\" tippen, um alle Ereignisse dieser Kategorie zu sehen","接收人: 你的 open_id (ou_ 开头) 或飞书登录邮箱":"Empfänger: deine open_id (beginnt mit ou_) oder Feishu-Login-E-Mail","推送内容：封面卡片（触发那帧图 + 信息，最快）":"Push-Inhalt: Cover-Karte (Auslösebild + Infos, am schnellsten)","推送内容：触发摄像头视频（可回放）":"Push-Inhalt: Video der Auslösekamera (abspielbar)","摄像头":"Kamera","收起详细数据 ⌃":"Details einklappen ⌃","改完本机会自动用新密码重新登录，手机/其它设备上的登录状态立即失效。":"Nach der Änderung meldet sich dieses Gerät automatisch mit dem neuen Passwort neu an; Anmeldungen auf Handy/weiteren Geräten werden sofort ungültig.","敏感信息已明文显示，注意别外发":"Sensible Daten im Klartext, beim Weitergeben aufpassen","敏感信息已隐藏（截图安全）":"Sensible Daten verborgen (screenshot-sicher)","新密码 (至少 6 位)":"Neues Passwort (mindestens 6 Zeichen)","方向盘角度":"Lenkwinkel","日期":"Datum","时间":"Zeit","昨天":"Gestern","暂无归档视频":"Noch keine archivierten Videos","暂无皮肤, 使用默认外观":"Keine Skins, Standarddarstellung aktiv","最新版本":"Neueste Version","有新版本":"Neue Version verfügbar","未标注原因":"Kein Grund angegeben","未检查":"Nicht geprüft","条":"Clips","查看链接前缀 (可选): http://你的域名:端口":"Link-Präfix (optional): http://deine-domain:port","检查中…":"Prüfe…","检查更新":"Nach Updates suchen","正在上传…":"Wird hochgeladen…","正在下载并校验新版本…":"Neue Version wird heruntergeladen und geprüft…","正在合成多画面视频":"Multi-View-Video wird erstellt","活动ID":"Ereignis-ID","浅色":"Hell","浏览和管理车机U盘 (特斯拉写入的镜像)。连接后会临时断开车机读取几秒，5 分钟无操作自动恢复。":"Auto-USB-Stick durchsuchen und verwalten (das von Tesla geschriebene Abbild). Beim Verbinden wird das Lesen durch das Auto einige Sekunden unterbrochen; nach 5 Minuten ohne Bedienung erfolgt die Wiederherstellung automatisch.","深色":"Dunkel","清空":"Leeren","点击行车记录仪图标":"Dashcam-Symbol angetippt","片段":"Clips","用户名":"Benutzername","用户名或密码不对":"Benutzername oder Passwort falsch","画面":"Ansichten","界面语言，保存在本机浏览器":"Sprache der Oberfläche, im Browser gespeichert","登录":"Anmelden","登录状态保留":"Anmeldung gemerkt für","盒子归档存储":"Box-Archivspeicher","确定要退出登录吗？":"Wirklich abmelden?","私聊推送 — 只有我本人能看到":"Privatnachricht — nur ich kann sie sehen","秒 (等片段写完再推)":"Sekunden (warten, bis Clips fertig geschrieben sind)","秒（从触发前 5 秒开始截）":"Sekunden (beginnt 5 s vor Auslösung)","立即升级":"Jetzt aktualisieren","群机器人 webhook (仅群推送需要): https://open.feishu.cn/open-apis/bot/v2/hook/...":"Gruppen-Bot-webhook (nur für Gruppen-Push): https://open.feishu.cn/open-apis/bot/v2/hook/...","群机器人 — 群里所有人都能看到":"Gruppen-Bot — für alle in der Gruppe sichtbar","自动":"Auto","行车记录":"Dashcam","行车记录仪菜单保存":"Speichern im Dashcam-Menü","视频时长":"Videolänge","视频清晰度：360p（约 1.8MB / 30 秒）":"Videoqualität: 360p (ca. 1,8MB / 30 s)","视频清晰度：480p（约 3MB / 30 秒）":"Videoqualität: 480p (ca. 3MB / 30 s)","视频清晰度：720p（约 5MB / 30 秒）":"Videoqualität: 720p (ca. 5MB / 30 s)","触发原因":"Auslösegrund","设为锁车音":"Als Verriegelungston festlegen","设备正在拼接各路画面, 请勿关闭页面":"Ansichten werden zusammengefügt, Seite nicht schließen","设置":"Einstellungen","该筛选下暂无事件":"Keine Ereignisse für diesen Filter","跳转":"Los","车机U盘未连接":"Auto-USB-Stick nicht verbunden","车机录制后, 归档同步任务会自动把视频收进来 (镜像需空闲10分钟)":"Nach der Aufnahme im Auto übernimmt die Archiv-Synchronisierung die Videos automatisch (Spiegelung benötigt 10 Min. Leerlauf)","车机要求单个音频 <1MB, 请裁剪后重试":"Das Auto verlangt Audio <1MB, bitte kürzen und erneut versuchen","车载U盘存储":"USB-Stick-Speicher","车门拉动":"Türzug","车门被拉动":"Tür bewegt","载入中…":"Wird geladen…","连接车机U盘":"Auto-USB-Stick verbinden","退出登录":"Abmelden","选择日期…":"Datum wählen…","选择要导出的画面":"Ansichten für den Export wählen","选择语言":"Sprache wählen","遭遇袭击":"Aufprall","遭遇袭击 (紧急报警)":"Aufprall (Notruf)","锁车音":"Verriegelungston","锁车音必须是 WAV (mp3 只能当喇叭音效)":"Verriegelungston muss WAV sein (mp3 nur als Boombox-Sound)","锁车音要求 WAV 44.1kHz 16-bit <1MB 1~5秒；LockChime.wav 写入车机U盘根目录，其它 mp3/wav 作为 Boombox 音效写入 Boombox/ 目录。文件在归档同步时写入车机U盘。":"Verriegelungston erfordert WAV 44.1kHz 16-bit <1MB 1–5 s; LockChime.wav kommt ins Stammverzeichnis des Auto-USB-Sticks, andere mp3/wav werden als Boombox-Sounds in den Ordner Boombox/ geschrieben. Dateien werden bei der Archiv-Synchronisierung auf den USB-Stick geschrieben.","门把手被拉动":"Türgriff gezogen","＋ 上传文件到当前目录 (任意类型, ≤100MB)":"＋ Datei in den aktuellen Ordner hochladen (beliebiger Typ, ≤100MB)","＋ 上传皮肤文件 (css/jpg/png/webp)":"＋ Skin-Datei hochladen (css/jpg/png/webp)","＋ 上传音频 (wav/mp3, <1MB)":"＋ Audio hochladen (wav/mp3, <1MB)","🌐 语言":"🌐 Sprache","🎨 网页背景":"🎨 Skin","👁 显示":"👁 Anzeigen","📂 文件":"📂 Dateien","🔄 更新":"🔄 Update","🔊 锁车语音":"🔊 Verriegelungston","🔑 账号":"🔑 Konto","🔔 推送":"🔔 Push","🗄 归档区":"🗄 Archivbereich","🙈 隐藏":"🙈 Ausblenden","🚗 特斯拉哨兵查看器":"🚗 TSL Sentry Viewer","🚗 车机U盘":"🚗 Auto-USB-Stick","归档":"Archiv","待确认":"Ausstehend","同步服务未运行":"Synchronisierungsdienst läuft nicht","路画面":"Kanalansicht","最近一次":"Letzter Lauf","未启用":"Nicht aktiviert","已启用私聊推送, 等下一个哨兵事件":"Direktnachrichten aktiviert, warte auf das nächste Sentry-Ereignis","已启用, 但接收人/应用凭据未配全":"Aktiviert, aber Empfänger-/App-Zugangsdaten unvollständig","读取设置失败":"Einstellungen konnten nicht geladen werden","私聊需要 App ID / Secret + 接收人":"Direktnachrichten benötigen App ID / Secret + Empfänger","请先填群机器人 webhook":"Bitte zuerst den Gruppenbot-Webhook eintragen","保存中…":"Speichern…","发送失败":"Senden fehlgeschlagen","正在发送测试卡片…":"Testkarte wird gesendet…","当前未开启登录保护, 设置密码后即开启":"Anmeldeschutz ist aus, mit einem Passwort wird er aktiviert","新密码至少 6 位":"Neues Passwort mindestens 6 Zeichen","两次输入的新密码不一致":"Die neuen Passwörter stimmen nicht überein","提交中…":"Wird übermittelt…","空目录":"Leerer Ordner","正在连接 GitHub…":"Verbindung zu GitHub…","检查失败":"Prüfung fehlgeschlagen","连不上 GitHub":"GitHub nicht erreichbar","(可稍后重试)":"(später erneut versuchen)","来源":"Quelle","升级失败":"Upgrade fehlgeschlagen","原密码不对":"Aktuelles Passwort ist falsch","修改失败":"Änderung fehlgeschlagen","上传失败":"Upload fehlgeschlagen","密码已更新, 其它设备需要重新登录":"Passwort aktualisiert, andere Geräte müssen sich neu anmelden","仅支持 css/jpg/png/webp":"Nur css/jpg/png/webp unterstützt","皮肤已上传并应用":"Skin hochgeladen und angewendet","文件超过 100MB 上限":"Datei überschreitet das Limit von 100 MB","车机U盘已连接 (已临时断开车机读取, 5分钟无操作自动恢复)":"USB-Stick im Fahrzeug verbunden (Fahrzeugzugriff vorübergehend getrennt, automatische Wiederherstellung nach 5 Minuten Inaktivität)","已恢复车机导出":"Fahrzeugexport wiederhergestellt","车机U盘未连接, 请先点「连接车机U盘」":"USB-Stick im Fahrzeug nicht verbunden, bitte zuerst 「USB-Stick im Fahrzeug verbinden」 antippen","归档里没有可用的片段":"Keine verwendbaren Clips im Archiv","请至少选择一路":"Bitte mindestens einen Kanal auswählen","已有合成在进行":"Zusammenführung läuft bereits","合成失败":"Zusammenführung fehlgeschlagen","已开始下载":"Download gestartet","此浏览器不支持本机合成, 请使用打包下载":"Dieser Browser unterstützt keine lokale Zusammenführung, bitte den Paket-Download verwenden","TSL哨兵云盘":"TSL Sentry Drive","合成完成":"Zusammenfügen fertig","路":{"en":"cams","de":"Kam.","fr":"cams","it":"cam","es":"cams","nl":"cam.","ru":"кам.","ja":"カメラ","ko":"카메라"}},"en":{"品牌":"Brand","App ID — cli_ 开头":"App ID — starts with cli_","App Secret (已保存则留空表示不修改)":"App Secret (leave blank to keep current)","‹ 返回":"‹ Back","⏳ 待写入车机U盘:":"⏳ Pending write to car USB:","▶ 轻触开始同步播放":"▶ Tap to start synced playback","⚙ 个性化":"⚙ Personalize","✅ 已写入:":"✅ Written:","上传 CSS 皮肤文件或背景图 (jpg/png/webp)。CSS 中引用图片请用 /skin-media/文件名。":"Upload a CSS skin file or background image (jpg/png/webp). Reference images in CSS as /skin-media/filename.","下载":"Download","下载清晰度":"Download quality","主题":"Theme","也推手动保存":"Also push manual saves","仅支持 wav/mp3":"Only wav/mp3 supported","仅限本人访问":"Owner access only","今天":"Today","位置":"Location","使用中":"Active","侦测到物体移动":"Object movement detected","侦测到碰撞/震动":"Impact/vibration detected","保存失败":"Save failed","保存设置":"Save settings","修改密码":"Change password","全选":"Select all","全部":"All","全部日期":"All dates","再输一次新密码":"Repeat new password","删除":"Delete","刹车":"Brake","刹车占比":"Brake %","前视":"Front","升级会从 GitHub 及多个镜像并发竞速拉取最新程序, 覆盖本机文件并自动重启服务 (约5秒); 配置、录像、登录信息不受影响。":"The upgrade fetches the latest build from GitHub and multiple mirrors in parallel, overwrites local files and restarts the service automatically (about 5 s); configs, recordings and login info are unaffected.","半透明单行: 时间/位置/车速/挡位/油门/刹车, 基本不挡画面":"Single semi-transparent line: time/location/speed/gear/throttle/brake, barely covers the view","单选取原文件直接下载(加水印时走本机合成)；多选合成一个多画面视频。下载/打包按所选清晰度导出(首次需等转码)。":"Single-select downloads the original file directly (with watermark it composites locally); multi-select merges one multi-view video. Downloads/zips export at the selected quality (first time may wait for transcoding).","原因":"Reason","原画":"Original","发送测试":"Send test","叠加行车信息水印":"Overlay driving data watermark","右B柱":"Right B-pillar","右前翼":"Right front fender","右翼子板":"Right fender","合成视频":"Merge video","同步状态":"Sync status","后视":"Rear","启用推送":"Enable push","哨兵告警":"Sentry alerts","哨兵模式触发":"Sentry mode triggered","哨兵触发时把时间/位置/触发原因和触发画面推到飞书。默认走自建应用私聊(只有你本人可见)；也可切到群机器人 webhook(群里都能看到)。视频推送只支持私聊。":"When Sentry triggers, pushes time/location, trigger reason and the trigger frame to Feishu. Defaults to private messages via your own app (only you can see them); you can also switch to a group bot webhook (visible to the whole group). Video push works for private messages only.","哨兵警觉":"Sentry aware","回滚到上一版本":"Roll back to previous version","天":"days","实时同步中":"Live syncing","密码":"Password","尝试次数过多，请 5 分钟后再试":"Too many attempts, try again in 5 minutes","展开详细数据 ⌄":"Show details ⌄","左B柱":"Left B-pillar","左前翼":"Left front fender","左翼子板":"Left fender","已保存":"Saved","已删除":"Deleted","已加入队列, 归档同步时写入车机U盘":"Queued, will be written to car USB during archive sync","已同步":"Synced","已是最新":"Up to date","延迟推送":"Push delay","当前密码":"Current password","当前版本":"Current version","恢复车机导出":"Restore car access","手动保存":"Manual save","打包zip":"Zip download","按喇叭保存":"Horn save","换个日期或点「全部」查看本分类所有事件":"Try another date or tap \"All\" to see all events in this category","接收人: 你的 open_id (ou_ 开头) 或飞书登录邮箱":"Recipient: your open_id (starts with ou_) or Feishu login email","推送内容：封面卡片（触发那帧图 + 信息，最快）":"Push content: cover card (trigger frame + info, fastest)","推送内容：触发摄像头视频（可回放）":"Push content: trigger camera video (playable)","摄像头":"Camera","收起详细数据 ⌃":"Hide details ⌃","改完本机会自动用新密码重新登录，手机/其它设备上的登录状态立即失效。":"After the change, this device logs back in with the new password automatically; login sessions on phones/other devices are invalidated immediately.","敏感信息已明文显示，注意别外发":"Sensitive info shown in plain text, be careful when sharing","敏感信息已隐藏（截图安全）":"Sensitive info hidden (screenshot-safe)","新密码 (至少 6 位)":"New password (at least 6 characters)","方向盘角度":"Steering angle","日期":"Date","时间":"Time","昨天":"Yesterday","暂无归档视频":"No archived videos yet","暂无皮肤, 使用默认外观":"No skins, using the default look","最新版本":"Latest version","有新版本":"New version available","未标注原因":"No reason tagged","未检查":"Not checked","条":"clips","查看链接前缀 (可选): http://你的域名:端口":"View link prefix (optional): http://your-domain:port","检查中…":"Checking…","检查更新":"Check for updates","正在上传…":"Uploading…","正在下载并校验新版本…":"Downloading and verifying new version…","正在合成多画面视频":"Compositing multi-view video","活动ID":"Event ID","浅色":"Light","浏览和管理车机U盘 (特斯拉写入的镜像)。连接后会临时断开车机读取几秒，5 分钟无操作自动恢复。":"Browse and manage the car USB drive (the mirror written by Tesla). Connecting briefly interrupts car read access for a few seconds; it auto-restores after 5 minutes of inactivity.","深色":"Dark","清空":"Clear","点击行车记录仪图标":"Dashcam icon tapped","片段":"Clips","用户名":"Username","用户名或密码不对":"Wrong username or password","画面":"Views","界面语言，保存在本机浏览器":"UI language, saved in this browser","登录":"Log in","登录状态保留":"Login remembered for","盒子归档存储":"Box archive storage","确定要退出登录吗？":"Are you sure you want to log out?","私聊推送 — 只有我本人能看到":"Direct message — only I can see it","秒 (等片段写完再推)":"seconds (wait for clips to finish writing)","秒（从触发前 5 秒开始截）":"seconds (starts 5 s before trigger)","立即升级":"Upgrade now","群机器人 webhook (仅群推送需要): https://open.feishu.cn/open-apis/bot/v2/hook/...":"Group bot webhook (group push only): https://open.feishu.cn/open-apis/bot/v2/hook/...","群机器人 — 群里所有人都能看到":"Group bot — everyone in the group can see it","自动":"Auto","行车记录":"Dashcam","行车记录仪菜单保存":"Dashcam menu save","视频时长":"Clip length","视频清晰度：360p（约 1.8MB / 30 秒）":"Video quality: 360p (~1.8MB / 30 s)","视频清晰度：480p（约 3MB / 30 秒）":"Video quality: 480p (~3MB / 30 s)","视频清晰度：720p（约 5MB / 30 秒）":"Video quality: 720p (~5MB / 30 s)","触发原因":"Trigger reason","设为锁车音":"Set as lock chime","设备正在拼接各路画面, 请勿关闭页面":"Stitching camera views, do not close this page","设置":"Settings","该筛选下暂无事件":"No events for this filter","跳转":"Go","车机U盘未连接":"Car USB not connected","车机录制后, 归档同步任务会自动把视频收进来 (镜像需空闲10分钟)":"After the car records, archive sync pulls in videos automatically (mirror needs 10 min idle)","车机要求单个音频 <1MB, 请裁剪后重试":"Car requires each audio file <1MB, trim it and retry","车载U盘存储":"USB drive storage","车门拉动":"Door pull","车门被拉动":"Door pulled","载入中…":"Loading…","连接车机U盘":"Connect car USB","退出登录":"Log out","选择日期…":"Pick a date…","选择要导出的画面":"Select views to export","选择语言":"Select language","遭遇袭击":"Impact","遭遇袭击 (紧急报警)":"Impact (panic alarm)","锁车音":"Lock chime","锁车音必须是 WAV (mp3 只能当喇叭音效)":"Lock chime must be WAV (mp3 only works as a Boombox sound)","锁车音要求 WAV 44.1kHz 16-bit <1MB 1~5秒；LockChime.wav 写入车机U盘根目录，其它 mp3/wav 作为 Boombox 音效写入 Boombox/ 目录。文件在归档同步时写入车机U盘。":"Lock chime requires WAV 44.1kHz 16-bit <1MB 1–5 s; LockChime.wav goes to the root of the car USB drive, other mp3/wav files are written to the Boombox/ folder as Boombox sounds. Files are written to the car USB during archive sync.","门把手被拉动":"Door handle pulled","＋ 上传文件到当前目录 (任意类型, ≤100MB)":"＋ Upload file to current folder (any type, ≤100MB)","＋ 上传皮肤文件 (css/jpg/png/webp)":"＋ Upload skin file (css/jpg/png/webp)","＋ 上传音频 (wav/mp3, <1MB)":"＋ Upload audio (wav/mp3, <1MB)","🌐 语言":"🌐 Language","🎨 网页背景":"🎨 Skin","👁 显示":"👁 Show","📂 文件":"📂 Files","🔄 更新":"🔄 Update","🔊 锁车语音":"🔊 Lock chime","🔑 账号":"🔑 Account","🔔 推送":"🔔 Push","🗄 归档区":"🗄 Archive area","🙈 隐藏":"🙈 Hide","🚗 特斯拉哨兵查看器":"🚗 TSL Sentry Viewer","🚗 车机U盘":"🚗 Car USB","归档":"Archive","待确认":"Pending","同步服务未运行":"Sync service not running","路画面":"Channel view","最近一次":"Last run","未启用":"Not enabled","已启用私聊推送, 等下一个哨兵事件":"Direct messages enabled, waiting for the next Sentry event","已启用, 但接收人/应用凭据未配全":"Enabled, but recipient/app credentials are incomplete","读取设置失败":"Failed to load settings","私聊需要 App ID / Secret + 接收人":"Direct messages need App ID / Secret + recipient","请先填群机器人 webhook":"Fill in the group bot webhook first","保存中…":"Saving…","发送失败":"Send failed","正在发送测试卡片…":"Sending test card…","当前未开启登录保护, 设置密码后即开启":"Login protection is off, set a password to enable it","新密码至少 6 位":"New password must be at least 6 characters","两次输入的新密码不一致":"New passwords do not match","提交中…":"Submitting…","空目录":"Empty folder","正在连接 GitHub…":"Connecting to GitHub…","检查失败":"Check failed","连不上 GitHub":"Cannot reach GitHub","(可稍后重试)":"(you can retry later)","来源":"Source","升级失败":"Upgrade failed","原密码不对":"Current password is incorrect","修改失败":"Update failed","上传失败":"Upload failed","密码已更新, 其它设备需要重新登录":"Password updated, other devices need to sign in again","仅支持 css/jpg/png/webp":"Only css/jpg/png/webp supported","皮肤已上传并应用":"Skin uploaded and applied","文件超过 100MB 上限":"File exceeds the 100 MB limit","车机U盘已连接 (已临时断开车机读取, 5分钟无操作自动恢复)":"Car USB drive connected (car access temporarily released, auto-restores after 5 minutes idle)","已恢复车机导出":"Car export restored","车机U盘未连接, 请先点「连接车机U盘」":"Car USB drive not connected, tap 「Connect car USB drive」 first","归档里没有可用的片段":"No usable clips in the archive","请至少选择一路":"Select at least one channel","已有合成在进行":"A merge is already in progress","合成失败":"Merge failed","已开始下载":"Download started","此浏览器不支持本机合成, 请使用打包下载":"This browser does not support local merging, use the packaged download","TSL哨兵云盘":"TSL Sentry Drive","合成完成":"Merge complete","路":{"en":"cams","de":"Kam.","fr":"cams","it":"cam","es":"cams","nl":"cam.","ru":"кам.","ja":"カメラ","ko":"카메라"}},"es":{"品牌":"Marca","App ID — cli_ 开头":"App ID — empieza por cli_","App Secret (已保存则留空表示不修改)":"App Secret (déjalo vacío para no cambiarlo)","‹ 返回":"‹ Volver","⏳ 待写入车机U盘:":"⏳ Pendiente de escribir en el USB del coche:","▶ 轻触开始同步播放":"▶ Toca para iniciar la reproducción sincronizada","⚙ 个性化":"⚙ Personalización","✅ 已写入:":"✅ Escritos:","上传 CSS 皮肤文件或背景图 (jpg/png/webp)。CSS 中引用图片请用 /skin-media/文件名。":"Sube un archivo de skin CSS o una imagen de fondo (jpg/png/webp). Para las imágenes en el CSS usa /skin-media/nombrearchivo.","下载":"Descargar","下载清晰度":"Calidad de descarga","主题":"Tema","也推手动保存":"También los guardados manuales","仅支持 wav/mp3":"Solo wav/mp3","仅限本人访问":"Acceso solo para el propietario","今天":"Hoy","位置":"Ubicación","使用中":"En uso","侦测到物体移动":"Movimiento detectado","侦测到碰撞/震动":"Colisión/vibración detectada","保存失败":"Error al guardar","保存设置":"Guardar ajustes","修改密码":"Cambiar contraseña","全选":"Seleccionar todo","全部":"Todos","全部日期":"Todas las fechas","再输一次新密码":"Repite la nueva contraseña","删除":"Eliminar","刹车":"Freno","刹车占比":"Porcentaje de freno","前视":"Delantera","升级会从 GitHub 及多个镜像并发竞速拉取最新程序, 覆盖本机文件并自动重启服务 (约5秒); 配置、录像、登录信息不受影响。":"La actualización descarga la última versión en paralelo desde GitHub y varios espejos, sobrescribe los archivos locales y reinicia el servicio (unos 5 s); la configuración, las grabaciones y el acceso no se ven afectados.","半透明单行: 时间/位置/车速/挡位/油门/刹车, 基本不挡画面":"Una línea semitransparente: hora/ubicación/velocidad/marcha/acelerador/freno, apenas tapa la imagen","单选取原文件直接下载(加水印时走本机合成)；多选合成一个多画面视频。下载/打包按所选清晰度导出(首次需等转码)。":"Con una sola selección descargas el archivo original (con marca de agua se compone en local); con varias se crea un único vídeo multivista. La descarga y el zip se exportan en la calidad elegida (la primera vez hay que esperar la transcodificación).","原因":"Motivo","原画":"Original","发送测试":"Enviar prueba","叠加行车信息水印":"Añadir marca de agua con datos de conducción","右B柱":"Pilar B der.","右前翼":"Aleta delantera der.","右翼子板":"Aleta der.","合成视频":"Unir vídeo","同步状态":"Estado de sync","后视":"Trasera","启用推送":"Activar notificaciones","哨兵告警":"Alertas Centinela","哨兵模式触发":"Activación del Centinela","哨兵触发时把时间/位置/触发原因和触发画面推到飞书。默认走自建应用私聊(只有你本人可见)；也可切到群机器人 webhook(群里都能看到)。视频推送只支持私聊。":"Cuando salta el Centinela envía a Feishu la hora/ubicación/causa y el fotograma del aviso. Por defecto usa la app privada (solo lo ves tú); también puedes cambiar al webhook de un bot de grupo (lo ve todo el grupo). El push de vídeo solo funciona en privado.","哨兵警觉":"Alerta centinela","回滚到上一版本":"Volver a la versión anterior","天":"días","实时同步中":"Sincronizando en vivo","密码":"Contraseña","尝试次数过多，请 5 分钟后再试":"Demasiados intentos, inténtalo en 5 minutos","展开详细数据 ⌄":"Mostrar datos detallados ⌄","左B柱":"Pilar B izq.","左前翼":"Aleta delantera izq.","左翼子板":"Aleta izq.","已保存":"Guardado","已删除":"Eliminado","已加入队列, 归档同步时写入车机U盘":"En cola, se escribirá en el USB del coche al sincronizar el archivo","已同步":"Sincronizado","已是最新":"Ya está actualizado","延迟推送":"Push retrasado","当前密码":"Contraseña actual","当前版本":"Versión actual","恢复车机导出":"Restaurar acceso del coche","手动保存":"Guardados manuales","打包zip":"Crear zip","按喇叭保存":"Guardado con claxon","换个日期或点「全部」查看本分类所有事件":"Cambia la fecha o toca «Todos» para ver todos los eventos de la categoría","接收人: 你的 open_id (ou_ 开头) 或飞书登录邮箱":"Destinatario: tu open_id (empieza por ou_) o el correo de acceso a Feishu","推送内容：封面卡片（触发那帧图 + 信息，最快）":"Contenido: tarjeta de portada (fotograma del aviso + info, lo más rápido)","推送内容：触发摄像头视频（可回放）":"Contenido: vídeo de la cámara que lo activó (reproducible)","摄像头":"Cámara","收起详细数据 ⌃":"Ocultar datos detallados ⌃","改完本机会自动用新密码重新登录，手机/其它设备上的登录状态立即失效。":"Tras el cambio, este dispositivo inicia sesión con la nueva contraseña; las sesiones del móvil y otros dispositivos se cierran al instante.","敏感信息已明文显示，注意别外发":"Datos sensibles a la vista, no los compartas","敏感信息已隐藏（截图安全）":"Datos sensibles ocultos (seguro para capturas)","新密码 (至少 6 位)":"Nueva contraseña (mínimo 6 caracteres)","方向盘角度":"Ángulo de dirección","日期":"Fecha","时间":"Hora","昨天":"Ayer","暂无归档视频":"No hay vídeos archivados","暂无皮肤, 使用默认外观":"Sin skins, aspecto predeterminado","最新版本":"Última versión","有新版本":"Nueva versión disponible","未标注原因":"Motivo no indicado","未检查":"Sin comprobar","条":"clips","查看链接前缀 (可选): http://你的域名:端口":"Prefijo del enlace de vista (opcional): http://tu-dominio:puerto","检查中…":"Comprobando…","检查更新":"Buscar actualizaciones","正在上传…":"Subiendo…","正在下载并校验新版本…":"Descargando y verificando la nueva versión…","正在合成多画面视频":"Creando vídeo multivista","活动ID":"ID del evento","浅色":"Claro","浏览和管理车机U盘 (特斯拉写入的镜像)。连接后会临时断开车机读取几秒，5 分钟无操作自动恢复。":"Explora y gestiona el USB del coche (la copia que escribe Tesla). Al conectar, el coche pierde el acceso unos segundos; se restaura tras 5 minutos sin actividad.","深色":"Oscuro","清空":"Deseleccionar todo","点击行车记录仪图标":"Toque en el icono Dashcam","片段":"Clips","用户名":"Usuario","用户名或密码不对":"Usuario o contraseña incorrectos","画面":"Vistas","界面语言，保存在本机浏览器":"Idioma de la interfaz, guardado en este navegador","登录":"Iniciar sesión","登录状态保留":"Mantener la sesión","盒子归档存储":"Espacio de archivo del box","确定要退出登录吗？":"¿Seguro que quieres cerrar sesión?","私聊推送 — 只有我本人能看到":"Push privado — solo lo ves tú","秒 (等片段写完再推)":"segundos (espera a que se escriban los clips)","秒（从触发前 5 秒开始截）":"segundos (desde 5 s antes del aviso)","立即升级":"Actualizar ahora","群机器人 webhook (仅群推送需要): https://open.feishu.cn/open-apis/bot/v2/hook/...":"webhook del bot de grupo (solo para push de grupo): https://open.feishu.cn/open-apis/bot/v2/hook/...","群机器人 — 群里所有人都能看到":"Bot de grupo — lo ve todo el grupo","自动":"Auto","行车记录":"Dashcam","行车记录仪菜单保存":"Guardado desde el menú Dashcam","视频时长":"Duración del vídeo","视频清晰度：360p（约 1.8MB / 30 秒）":"Calidad de vídeo: 360p (unos 1.8MB / 30 s)","视频清晰度：480p（约 3MB / 30 秒）":"Calidad de vídeo: 480p (unos 3MB / 30 s)","视频清晰度：720p（约 5MB / 30 秒）":"Calidad de vídeo: 720p (unos 5MB / 30 s)","触发原因":"Causa de activación","设为锁车音":"Usar como sonido al cerrar","设备正在拼接各路画面, 请勿关闭页面":"El dispositivo está uniendo las vistas, no cierres la página","设置":"Ajustes","该筛选下暂无事件":"No hay eventos con este filtro","跳转":"Ir","车机U盘未连接":"USB del coche no conectado","车机录制后, 归档同步任务会自动把视频收进来 (镜像需空闲10分钟)":"Tras grabar el coche, la sincronización del archivo recoge los vídeos (el espejo debe estar inactivo 10 minutos)","车机要求单个音频 <1MB, 请裁剪后重试":"El coche exige audio <1MB, recorta el archivo e inténtalo de nuevo","车载U盘存储":"Espacio USB del coche","车门拉动":"Puerta forzada","车门被拉动":"Puerta manipulada","载入中…":"Cargando…","连接车机U盘":"Conectar USB del coche","退出登录":"Cerrar sesión","选择日期…":"Elegir fecha…","选择要导出的画面":"Elige las vistas que quieres exportar","选择语言":"Elegir idioma","遭遇袭击":"Agresión","遭遇袭击 (紧急报警)":"Agresión (alarma de emergencia)","锁车音":"Sonido al cerrar","锁车音必须是 WAV (mp3 只能当喇叭音效)":"El sonido al cerrar debe ser WAV (mp3 solo como efecto de claxon)","锁车音要求 WAV 44.1kHz 16-bit <1MB 1~5秒；LockChime.wav 写入车机U盘根目录，其它 mp3/wav 作为 Boombox 音效写入 Boombox/ 目录。文件在归档同步时写入车机U盘。":"El sonido al cerrar debe ser WAV 44.1kHz 16-bit <1MB 1~5 s; LockChime.wav se escribe en la raíz del USB del coche y los demás mp3/wav como efectos de Boombox en la carpeta Boombox/. Los archivos se escriben en el USB del coche al sincronizar el archivo.","门把手被拉动":"Manilla accionada","＋ 上传文件到当前目录 (任意类型, ≤100MB)":"＋ Subir archivo a la carpeta actual (cualquier tipo, ≤100MB)","＋ 上传皮肤文件 (css/jpg/png/webp)":"＋ Subir archivo de skin (css/jpg/png/webp)","＋ 上传音频 (wav/mp3, <1MB)":"＋ Subir audio (wav/mp3, <1MB)","🌐 语言":"🌐 Idioma","🎨 网页背景":"🎨 Apariencia","👁 显示":"👁 Mostrar","📂 文件":"📂 Archivos","🔄 更新":"🔄 Actualización","🔊 锁车语音":"🔊 Sonido al cerrar","🔑 账号":"🔑 Cuenta","🔔 推送":"🔔 Notificaciones","🗄 归档区":"🗄 Archivo","🙈 隐藏":"🙈 Ocultar","🚗 特斯拉哨兵查看器":"🚗 Visor Centinela Tesla","🚗 车机U盘":"🚗 USB del coche","归档":"Archivo","待确认":"Pendiente de confirmar","同步服务未运行":"Servicio de sincronización no activo","路画面":"Vista de canal","最近一次":"Última vez","未启用":"No activado","已启用私聊推送, 等下一个哨兵事件":"Avisos privados activados, esperando el próximo evento Centinela","已启用, 但接收人/应用凭据未配全":"Activado, pero faltan destinatarios o credenciales de la app","读取设置失败":"No se pudo leer la configuración","私聊需要 App ID / Secret + 接收人":"Los avisos privados requieren App ID / Secret + destinatario","请先填群机器人 webhook":"Primero rellena el webhook del bot de grupo","保存中…":"Guardando…","发送失败":"Error al enviar","正在发送测试卡片…":"Enviando tarjeta de prueba…","当前未开启登录保护, 设置密码后即开启":"Protección de acceso desactivada: se activa al definir una contraseña","新密码至少 6 位":"La nueva contraseña debe tener al menos 6 caracteres","两次输入的新密码不一致":"Las contraseñas nuevas no coinciden","提交中…":"Enviando…","空目录":"Carpeta vacía","正在连接 GitHub…":"Conectando con GitHub…","检查失败":"Error en la comprobación","连不上 GitHub":"No se puede conectar con GitHub","(可稍后重试)":"(puedes reintentarlo más tarde)","来源":"Origen","升级失败":"Error en la actualización","原密码不对":"La contraseña actual es incorrecta","修改失败":"Error al modificar","上传失败":"Error al subir","密码已更新, 其它设备需要重新登录":"Contraseña actualizada, los demás dispositivos deben volver a iniciar sesión","仅支持 css/jpg/png/webp":"Solo css/jpg/png/webp","皮肤已上传并应用":"Tema subido y aplicado","文件超过 100MB 上限":"El archivo supera el límite de 100MB","车机U盘已连接 (已临时断开车机读取, 5分钟无操作自动恢复)":"Memoria USB del coche conectada (lectura del coche interrumpida, se restaura automáticamente tras 5 minutos sin actividad)","已恢复车机导出":"Exportación del coche restaurada","车机U盘未连接, 请先点「连接车机U盘」":"Memoria USB del coche no conectada, pulsa antes «Conectar memoria USB del coche»","归档里没有可用的片段":"No hay clips disponibles en el archivo","请至少选择一路":"Selecciona al menos un canal","已有合成在进行":"Ya hay una composición en curso","合成失败":"Error en la composición","已开始下载":"Descarga iniciada","此浏览器不支持本机合成, 请使用打包下载":"Este navegador no admite la composición local, usa la descarga empaquetada","TSL哨兵云盘":"TSL Sentry Drive","合成完成":"Unión completada","路":{"en":"cams","de":"Kam.","fr":"cams","it":"cam","es":"cams","nl":"cam.","ru":"кам.","ja":"カメラ","ko":"카메라"}},"fr":{"品牌":"Marque","App ID — cli_ 开头":"App ID — commence par cli_","App Secret (已保存则留空表示不修改)":"App Secret (laisser vide pour ne pas modifier)","‹ 返回":"‹ Retour","⏳ 待写入车机U盘:":"⏳ En attente d'écriture sur l'USB :","▶ 轻触开始同步播放":"▶ Touchez pour lancer la lecture synchro","⚙ 个性化":"⚙ Personnalisation","✅ 已写入:":"✅ Écrit :","上传 CSS 皮肤文件或背景图 (jpg/png/webp)。CSS 中引用图片请用 /skin-media/文件名。":"Chargez un fichier de skin CSS ou une image de fond (jpg/png/webp). Dans le CSS, référencez les images via /skin-media/nomfichier.","下载":"Télécharger","下载清晰度":"Qualité de téléchargement","主题":"Thème","也推手动保存":"Notifier aussi les enregistrements manuels","仅支持 wav/mp3":"Formats acceptés : wav/mp3","仅限本人访问":"Accès réservé au propriétaire","今天":"Aujourd'hui","位置":"Position","使用中":"Actif","侦测到物体移动":"Mouvement détecté","侦测到碰撞/震动":"Impact/vibration détecté","保存失败":"Échec de l'enregistrement","保存设置":"Enregistrer les réglages","修改密码":"Modifier le mot de passe","全选":"Tout sélectionner","全部":"Tout","全部日期":"Toutes les dates","再输一次新密码":"Ressaisir le nouveau mot de passe","删除":"Supprimer","刹车":"Frein","刹车占比":"% de freinage","前视":"Avant","升级会从 GitHub 及多个镜像并发竞速拉取最新程序, 覆盖本机文件并自动重启服务 (约5秒); 配置、录像、登录信息不受影响。":"La mise à jour récupère la dernière version depuis GitHub et plusieurs miroirs en parallèle, remplace les fichiers locaux et redémarre le service automatiquement (environ 5 s) ; configuration, enregistrements et connexion restent inchangés.","半透明单行: 时间/位置/车速/挡位/油门/刹车, 基本不挡画面":"Ligne semi-transparente : heure/position/vitesse/rapport/pédale/frein, gêne à peine la vue","单选取原文件直接下载(加水印时走本机合成)；多选合成一个多画面视频。下载/打包按所选清晰度导出(首次需等转码)。":"Sélection simple : téléchargement du fichier original (avec filigrane, composition locale) ; sélection multiple : fusion en une vidéo multi-vues. Téléchargement/zip exportés à la qualité choisie (première fois : attente de transcodage).","原因":"Motif","原画":"Originale","发送测试":"Envoyer un test","叠加行车信息水印":"Incruster les infos de conduite","右B柱":"Montant B droit","右前翼":"Aile avant droite","右翼子板":"Aile droite","合成视频":"Fusionner en vidéo","同步状态":"État de synchronisation","后视":"Arrière","启用推送":"Activer les notifications","哨兵告警":"Alertes Sentry","哨兵模式触发":"Mode Sentry déclenché","哨兵触发时把时间/位置/触发原因和触发画面推到飞书。默认走自建应用私聊(只有你本人可见)；也可切到群机器人 webhook(群里都能看到)。视频推送只支持私聊。":"Au déclenchement Sentry, envoie heure/position, motif de déclenchement et image du déclenchement vers Feishu. Par défaut, messages privés via votre propre app (visibles par vous seul) ; sinon webhook de bot de groupe (visible par tout le groupe). L'envoi vidéo fonctionne uniquement en privé.","哨兵警觉":"Vigilance Sentry","回滚到上一版本":"Revenir à la version précédente","天":"jours","实时同步中":"Synchro en cours","密码":"Mot de passe","尝试次数过多，请 5 分钟后再试":"Trop de tentatives, réessayez dans 5 minutes","展开详细数据 ⌄":"Déplier les détails ⌄","左B柱":"Montant B gauche","左前翼":"Aile avant gauche","左翼子板":"Aile gauche","已保存":"Enregistré","已删除":"Supprimé","已加入队列, 归档同步时写入车机U盘":"En file d'attente, écrit sur l'USB voiture lors de la synchro d'archive","已同步":"Synchronisé","已是最新":"À jour","延迟推送":"Délai d'envoi","当前密码":"Mot de passe actuel","当前版本":"Version actuelle","恢复车机导出":"Restaurer l'accès voiture","手动保存":"Enregistrement manuel","打包zip":"Archive zip","按喇叭保存":"Enregistrement au klaxon","换个日期或点「全部」查看本分类所有事件":"Choisissez une autre date ou touchez « Tout » pour voir tous les événements de cette catégorie","接收人: 你的 open_id (ou_ 开头) 或飞书登录邮箱":"Destinataire : votre open_id (commence par ou_) ou e-mail de connexion Feishu","推送内容：封面卡片（触发那帧图 + 信息，最快）":"Contenu : carte de couverture (image du déclenchement + infos, le plus rapide)","推送内容：触发摄像头视频（可回放）":"Contenu : vidéo de la caméra de déclenchement (lecture possible)","摄像头":"Caméra","收起详细数据 ⌃":"Réduire les détails ⌃","改完本机会自动用新密码重新登录，手机/其它设备上的登录状态立即失效。":"Après la modification, cet appareil se reconnecte automatiquement avec le nouveau mot de passe ; les sessions sur mobile/autres appareils sont immédiatement invalidées.","敏感信息已明文显示，注意别外发":"Infos sensibles en clair, attention au partage","敏感信息已隐藏（截图安全）":"Infos sensibles masquées (sûr pour captures)","新密码 (至少 6 位)":"Nouveau mot de passe (6 caractères minimum)","方向盘角度":"Angle du volant","日期":"Date","时间":"Heure","昨天":"Hier","暂无归档视频":"Aucune vidéo archivée","暂无皮肤, 使用默认外观":"Aucun skin, apparence par défaut","最新版本":"Dernière version","有新版本":"Nouvelle version disponible","未标注原因":"Motif non renseigné","未检查":"Non vérifié","条":"clips","查看链接前缀 (可选): http://你的域名:端口":"Préfixe du lien de visualisation (optionnel) : http://votre-domaine:port","检查中…":"Vérification…","检查更新":"Rechercher des mises à jour","正在上传…":"Envoi en cours…","正在下载并校验新版本…":"Téléchargement et vérification de la nouvelle version…","正在合成多画面视频":"Fusion de la vidéo multi-vues","活动ID":"ID d'événement","浅色":"Clair","浏览和管理车机U盘 (特斯拉写入的镜像)。连接后会临时断开车机读取几秒，5 分钟无操作自动恢复。":"Parcourez et gérez l'USB voiture (le miroir écrit par Tesla). La connexion interrompt brièvement la lecture par la voiture quelques secondes ; restauration automatique après 5 minutes d'inactivité.","深色":"Sombre","清空":"Vider","点击行车记录仪图标":"Icône dashcam touchée","片段":"Clips","用户名":"Nom d'utilisateur","用户名或密码不对":"Nom d'utilisateur ou mot de passe incorrect","画面":"Vues","界面语言，保存在本机浏览器":"Langue de l'interface, mémorisée dans ce navigateur","登录":"Se connecter","登录状态保留":"Connexion conservée","盒子归档存储":"Stockage archive Box","确定要退出登录吗？":"Voulez-vous vraiment vous déconnecter ?","私聊推送 — 只有我本人能看到":"Message privé — visible uniquement par moi","秒 (等片段写完再推)":"secondes (attendre la fin d'écriture des clips)","秒（从触发前 5 秒开始截）":"secondes (commence 5 s avant le déclenchement)","立即升级":"Mettre à jour maintenant","群机器人 webhook (仅群推送需要): https://open.feishu.cn/open-apis/bot/v2/hook/...":"Webhook du bot de groupe (groupes uniquement) : https://open.feishu.cn/open-apis/bot/v2/hook/...","群机器人 — 群里所有人都能看到":"Bot de groupe — visible par tous dans le groupe","自动":"Auto","行车记录":"Dashcam","行车记录仪菜单保存":"Enregistrement via menu dashcam","视频时长":"Durée de la vidéo","视频清晰度：360p（约 1.8MB / 30 秒）":"Qualité vidéo : 360p (~1,8MB / 30 s)","视频清晰度：480p（约 3MB / 30 秒）":"Qualité vidéo : 480p (~3MB / 30 s)","视频清晰度：720p（约 5MB / 30 秒）":"Qualité vidéo : 720p (~5MB / 30 s)","触发原因":"Motif de déclenchement","设为锁车音":"Définir comme son de verrouillage","设备正在拼接各路画面, 请勿关闭页面":"Assemblage des vues en cours, ne fermez pas la page","设置":"Paramètres","该筛选下暂无事件":"Aucun événement pour ce filtre","跳转":"Aller","车机U盘未连接":"USB voiture non connecté","车机录制后, 归档同步任务会自动把视频收进来 (镜像需空闲10分钟)":"Après enregistrement par la voiture, la synchro d'archive importe les vidéos automatiquement (le miroir doit être inactif 10 min)","车机要求单个音频 <1MB, 请裁剪后重试":"La voiture exige un audio <1MB, raccourcissez et réessayez","车载U盘存储":"Stockage USB embarqué","车门拉动":"Tirage de portière","车门被拉动":"Portière manipulée","载入中…":"Chargement…","连接车机U盘":"Connecter l'USB voiture","退出登录":"Se déconnecter","选择日期…":"Choisir une date…","选择要导出的画面":"Choisir les vues à exporter","选择语言":"Choisir la langue","遭遇袭击":"Impact","遭遇袭击 (紧急报警)":"Impact (alarme d'urgence)","锁车音":"Son de verrouillage","锁车音必须是 WAV (mp3 只能当喇叭音效)":"Le son de verrouillage doit être WAV (mp3 réservé aux sons Boombox)","锁车音要求 WAV 44.1kHz 16-bit <1MB 1~5秒；LockChime.wav 写入车机U盘根目录，其它 mp3/wav 作为 Boombox 音效写入 Boombox/ 目录。文件在归档同步时写入车机U盘。":"Le son de verrouillage exige WAV 44.1kHz 16-bit <1MB 1 à 5 s ; LockChime.wav va à la racine de l'USB voiture, les autres mp3/wav sont écrits dans le dossier Boombox/ comme sons Boombox. Les fichiers sont écrits sur l'USB voiture lors de la synchro d'archive.","门把手被拉动":"Poignée tirée","＋ 上传文件到当前目录 (任意类型, ≤100MB)":"＋ Charger un fichier ici (tout type, ≤100MB)","＋ 上传皮肤文件 (css/jpg/png/webp)":"＋ Charger un fichier de skin (css/jpg/png/webp)","＋ 上传音频 (wav/mp3, <1MB)":"＋ Charger un audio (wav/mp3, <1MB)","🌐 语言":"🌐 Langue","🎨 网页背景":"🎨 Habillage","👁 显示":"👁 Afficher","📂 文件":"📂 Fichiers","🔄 更新":"🔄 Mise à jour","🔊 锁车语音":"🔊 Son de verrouillage","🔑 账号":"🔑 Compte","🔔 推送":"🔔 Notifications","🗄 归档区":"🗄 Zone d'archive","🙈 隐藏":"🙈 Masquer","🚗 特斯拉哨兵查看器":"🚗 TSL Sentry Viewer","🚗 车机U盘":"🚗 USB voiture","归档":"Archives","待确认":"En attente","同步服务未运行":"Service de synchronisation inactif","路画面":"Vue par canal","最近一次":"Dernière exécution","未启用":"Non activé","已启用私聊推送, 等下一个哨兵事件":"Messages privés activés, en attente du prochain événement Sentry","已启用, 但接收人/应用凭据未配全":"Activé, mais destinataire/identifiants d'application incomplets","读取设置失败":"Échec du chargement des paramètres","私聊需要 App ID / Secret + 接收人":"Les messages privés nécessitent App ID / Secret + destinataire","请先填群机器人 webhook":"Renseignez d'abord le webhook du bot de groupe","保存中…":"Enregistrement…","发送失败":"Échec de l'envoi","正在发送测试卡片…":"Envoi de la carte de test…","当前未开启登录保护, 设置密码后即开启":"La protection de connexion est désactivée, définissez un mot de passe pour l'activer","新密码至少 6 位":"Nouveau mot de passe : 6 caractères minimum","两次输入的新密码不一致":"Les nouveaux mots de passe ne correspondent pas","提交中…":"Envoi…","空目录":"Dossier vide","正在连接 GitHub…":"Connexion à GitHub…","检查失败":"Échec de la vérification","连不上 GitHub":"GitHub inaccessible","(可稍后重试)":"(réessayez plus tard)","来源":"Source","升级失败":"Échec de la mise à niveau","原密码不对":"Mot de passe actuel incorrect","修改失败":"Échec de la modification","上传失败":"Échec du téléversement","密码已更新, 其它设备需要重新登录":"Mot de passe mis à jour, les autres appareils doivent se reconnecter","仅支持 css/jpg/png/webp":"Seuls css/jpg/png/webp sont pris en charge","皮肤已上传并应用":"Skin téléversé et appliqué","文件超过 100MB 上限":"Le fichier dépasse la limite de 100 Mo","车机U盘已连接 (已临时断开车机读取, 5分钟无操作自动恢复)":"Clé USB du véhicule connectée (accès véhicule temporairement libéré, rétablissement automatique après 5 minutes d'inactivité)","已恢复车机导出":"Export véhicule rétabli","车机U盘未连接, 请先点「连接车机U盘」":"Clé USB du véhicule non connectée, touchez d'abord 「Connecter la clé USB du véhicule」","归档里没有可用的片段":"Aucun clip utilisable dans les archives","请至少选择一路":"Sélectionnez au moins un canal","已有合成在进行":"Une fusion est déjà en cours","合成失败":"Échec de la fusion","已开始下载":"Téléchargement démarré","此浏览器不支持本机合成, 请使用打包下载":"Ce navigateur ne prend pas en charge la fusion locale, utilisez le téléchargement groupé","TSL哨兵云盘":"TSL Sentry Drive","合成完成":"Fusion terminée","路":{"en":"cams","de":"Kam.","fr":"cams","it":"cam","es":"cams","nl":"cam.","ru":"кам.","ja":"カメラ","ko":"카메라"}},"it":{"品牌":"Marchio","App ID — cli_ 开头":"App ID — inizia con cli_","App Secret (已保存则留空表示不修改)":"App Secret (lascia vuoto per non modificarlo)","‹ 返回":"‹ Indietro","⏳ 待写入车机U盘:":"⏳ Da scrivere sull'USB dell'auto:","▶ 轻触开始同步播放":"▶ Tocca per avviare la riproduzione sincronizzata","⚙ 个性化":"⚙ Personalizzazione","✅ 已写入:":"✅ Scritti:","上传 CSS 皮肤文件或背景图 (jpg/png/webp)。CSS 中引用图片请用 /skin-media/文件名。":"Carica un file skin CSS o un'immagine di sfondo (jpg/png/webp). Per le immagini nei CSS usa /skin-media/nomefile.","下载":"Scarica","下载清晰度":"Qualità download","主题":"Tema","也推手动保存":"Anche i salvataggi manuali","仅支持 wav/mp3":"Solo wav/mp3","仅限本人访问":"Accesso riservato al proprietario","今天":"Oggi","位置":"Posizione","使用中":"In uso","侦测到物体移动":"Movimento rilevato","侦测到碰撞/震动":"Collisione/urto rilevato","保存失败":"Salvataggio non riuscito","保存设置":"Salva impostazioni","修改密码":"Cambia password","全选":"Seleziona tutto","全部":"Tutti","全部日期":"Tutte le date","再输一次新密码":"Ripeti la nuova password","删除":"Elimina","刹车":"Freno","刹车占比":"Percentuale frenata","前视":"Anteriore","升级会从 GitHub 及多个镜像并发竞速拉取最新程序, 覆盖本机文件并自动重启服务 (约5秒); 配置、录像、登录信息不受影响。":"L'aggiornamento scarica l'ultima versione in parallelo da GitHub e da più mirror, sovrascrive i file locali e riavvia il servizio (circa 5 s); configurazione, registrazioni e accesso restano invariati.","半透明单行: 时间/位置/车速/挡位/油门/刹车, 基本不挡画面":"Una riga semitrasparente: ora/posizione/velocità/marcia/acceleratore/freno, non copre quasi nulla","单选取原文件直接下载(加水印时走本机合成)；多选合成一个多画面视频。下载/打包按所选清晰度导出(首次需等转码)。":"Con una sola selezione scarichi il file originale (con watermark viene ricomposto in locale); con più selezioni crei un unico video multi-vista. Download e zip esportano alla qualità scelta (la prima volta serve la transcodifica).","原因":"Motivo","原画":"Originale","发送测试":"Invia test","叠加行车信息水印":"Aggiungi watermark con i dati di guida","右B柱":"B-pilastro dx","右前翼":"Parafango ant. dx","右翼子板":"Parafango dx","合成视频":"Unisci video","同步状态":"Stato sync","后视":"Posteriore","启用推送":"Attiva notifiche","哨兵告警":"Avvisi Sentinella","哨兵模式触发":"Attivazione Sentinella","哨兵触发时把时间/位置/触发原因和触发画面推到飞书。默认走自建应用私聊(只有你本人可见)；也可切到群机器人 webhook(群里都能看到)。视频推送只支持私聊。":"Quando scatta la Sentinella invia a Feishu ora/posizione/causa e il frame del trigger. Per impostazione predefinita usa l'app privata (lo vedi solo tu); puoi passare al webhook di un bot di gruppo (lo vede tutto il gruppo). Il push dei video è solo in privato.","哨兵警觉":"Allerta sentinella","回滚到上一版本":"Torna alla versione precedente","天":"giorni","实时同步中":"Sync in tempo reale","密码":"Password","尝试次数过多，请 5 分钟后再试":"Troppi tentativi, riprova tra 5 minuti","展开详细数据 ⌄":"Mostra dati dettagliati ⌄","左B柱":"B-pilastro sx","左前翼":"Parafango ant. sx","左翼子板":"Parafango sx","已保存":"Salvato","已删除":"Eliminato","已加入队列, 归档同步时写入车机U盘":"Aggiunto in coda, verrà scritto sull'USB dell'auto durante la sincronizzazione archivio","已同步":"Sincronizzato","已是最新":"Già aggiornato","延迟推送":"Push ritardato","当前密码":"Password attuale","当前版本":"Versione attuale","恢复车机导出":"Ripristina accesso auto","手动保存":"Salvataggi manuali","打包zip":"Crea zip","按喇叭保存":"Salvataggio con clacson","换个日期或点「全部」查看本分类所有事件":"Cambia data o tocca «Tutti» per vedere tutti gli eventi della categoria","接收人: 你的 open_id (ou_ 开头) 或飞书登录邮箱":"Destinatario: il tuo open_id (inizia con ou_) o l'email di accesso Feishu","推送内容：封面卡片（触发那帧图 + 信息，最快）":"Contenuto: scheda copertina (frame del trigger + info, il più veloce)","推送内容：触发摄像头视频（可回放）":"Contenuto: video della telecamera che ha attivato (riproducibile)","摄像头":"Telecamera","收起详细数据 ⌃":"Nascondi dati dettagliati ⌃","改完本机会自动用新密码重新登录，手机/其它设备上的登录状态立即失效。":"Dopo la modifica questo dispositivo accede automaticamente con la nuova password; le sessioni su telefono e altri dispositivi decadono subito.","敏感信息已明文显示，注意别外发":"Dati sensibili in chiaro, non condividerli","敏感信息已隐藏（截图安全）":"Dati sensibili nascosti (sicuro per gli screenshot)","新密码 (至少 6 位)":"Nuova password (almeno 6 caratteri)","方向盘角度":"Angolo sterzo","日期":"Data","时间":"Ora","昨天":"Ieri","暂无归档视频":"Nessun video archiviato","暂无皮肤, 使用默认外观":"Nessuna skin, aspetto predefinito","最新版本":"Ultima versione","有新版本":"Nuova versione disponibile","未标注原因":"Motivo non indicato","未检查":"Non verificato","条":"clip","查看链接前缀 (可选): http://你的域名:端口":"Prefisso link di visualizzazione (facoltativo): http://tuo-dominio:porta","检查中…":"Controllo…","检查更新":"Controlla aggiornamenti","正在上传…":"Caricamento in corso…","正在下载并校验新版本…":"Download e verifica della nuova versione…","正在合成多画面视频":"Creazione video multi-vista in corso","活动ID":"ID evento","浅色":"Chiaro","浏览和管理车机U盘 (特斯拉写入的镜像)。连接后会临时断开车机读取几秒，5 分钟无操作自动恢复。":"Sfoglia e gestisci l'USB dell'auto (la copia scritta da Tesla). Al collegamento l'auto perde l'accesso per qualche secondo; dopo 5 minuti di inattività viene ripristinato.","深色":"Scuro","清空":"Deseleziona tutto","点击行车记录仪图标":"Tocco sull'icona Dashcam","片段":"Clip","用户名":"Nome utente","用户名或密码不对":"Nome utente o password errati","画面":"Viste","界面语言，保存在本机浏览器":"Lingua dell'interfaccia, salvata in questo browser","登录":"Accedi","登录状态保留":"Mantieni l'accesso per","盒子归档存储":"Spazio archivio box","确定要退出登录吗？":"Vuoi davvero uscire?","私聊推送 — 只有我本人能看到":"Push in privato — visibile solo a te","秒 (等片段写完再推)":"secondi (attendi la scrittura delle clip)","秒（从触发前 5 秒开始截）":"secondi (a partire da 5 s prima del trigger)","立即升级":"Aggiorna ora","群机器人 webhook (仅群推送需要): https://open.feishu.cn/open-apis/bot/v2/hook/...":"webhook bot di gruppo (solo per push di gruppo): https://open.feishu.cn/open-apis/bot/v2/hook/...","群机器人 — 群里所有人都能看到":"Bot di gruppo — visibile a tutto il gruppo","自动":"Auto","行车记录":"Dashcam","行车记录仪菜单保存":"Salvataggio dal menu Dashcam","视频时长":"Durata video","视频清晰度：360p（约 1.8MB / 30 秒）":"Qualità video: 360p (circa 1.8MB / 30 s)","视频清晰度：480p（约 3MB / 30 秒）":"Qualità video: 480p (circa 3MB / 30 s)","视频清晰度：720p（约 5MB / 30 秒）":"Qualità video: 720p (circa 5MB / 30 s)","触发原因":"Causa attivazione","设为锁车音":"Imposta come suono di chiusura","设备正在拼接各路画面, 请勿关闭页面":"Il dispositivo sta unendo le viste, non chiudere la pagina","设置":"Impostazioni","该筛选下暂无事件":"Nessun evento con questo filtro","跳转":"Vai","车机U盘未连接":"USB dell'auto non connesso","车机录制后, 归档同步任务会自动把视频收进来 (镜像需空闲10分钟)":"Dopo la registrazione dell'auto, la sincronizzazione archivio importa i video (il mirror deve restare inattivo 10 minuti)","车机要求单个音频 <1MB, 请裁剪后重试":"L'auto richiede file audio <1MB, taglia il file e riprova","车载U盘存储":"Spazio USB auto","车门拉动":"Portiera forzata","车门被拉动":"Portiera tirata","载入中…":"Caricamento…","连接车机U盘":"Collega USB auto","退出登录":"Esci","选择日期…":"Scegli data…","选择要导出的画面":"Scegli le viste da esportare","选择语言":"Scegli la lingua","遭遇袭击":"Aggressione","遭遇袭击 (紧急报警)":"Aggressione (allarme di emergenza)","锁车音":"Suono di chiusura","锁车音必须是 WAV (mp3 只能当喇叭音效)":"Il suono di chiusura deve essere WAV (mp3 solo come effetto clacson)","锁车音要求 WAV 44.1kHz 16-bit <1MB 1~5秒；LockChime.wav 写入车机U盘根目录，其它 mp3/wav 作为 Boombox 音效写入 Boombox/ 目录。文件在归档同步时写入车机U盘。":"Il suono di chiusura richiede WAV 44.1kHz 16-bit <1MB 1~5 s; LockChime.wav viene scritto nella radice dell'USB dell'auto, gli altri mp3/wav come effetti Boombox nella cartella Boombox/. I file vengono scritti sull'USB dell'auto durante la sincronizzazione archivio.","门把手被拉动":"Maniglia tirata","＋ 上传文件到当前目录 (任意类型, ≤100MB)":"＋ Carica file nella cartella corrente (qualsiasi tipo, ≤100MB)","＋ 上传皮肤文件 (css/jpg/png/webp)":"＋ Carica file skin (css/jpg/png/webp)","＋ 上传音频 (wav/mp3, <1MB)":"＋ Carica audio (wav/mp3, <1MB)","🌐 语言":"🌐 Lingua","🎨 网页背景":"🎨 Tema grafico","👁 显示":"👁 Mostra","📂 文件":"📂 File","🔄 更新":"🔄 Aggiornamenti","🔊 锁车语音":"🔊 Suono di chiusura","🔑 账号":"🔑 Account","🔔 推送":"🔔 Notifiche","🗄 归档区":"🗄 Archivio","🙈 隐藏":"🙈 Nascondi","🚗 特斯拉哨兵查看器":"🚗 Visualizzatore Sentinella Tesla","🚗 车机U盘":"🚗 USB auto","归档":"Archivio","待确认":"Da confermare","同步服务未运行":"Servizio di sincronizzazione non attivo","路画面":"Vista canale","最近一次":"Ultima volta","未启用":"Non attivo","已启用私聊推送, 等下一个哨兵事件":"Notifiche private attive, in attesa del prossimo evento Sentinella","已启用, 但接收人/应用凭据未配全":"Attivo, ma destinatari/credenziali app incompleti","读取设置失败":"Lettura impostazioni non riuscita","私聊需要 App ID / Secret + 接收人":"I messaggi privati richiedono App ID / Secret + destinatario","请先填群机器人 webhook":"Compila prima il webhook del bot di gruppo","保存中…":"Salvataggio…","发送失败":"Invio non riuscito","正在发送测试卡片…":"Invio della card di test…","当前未开启登录保护, 设置密码后即开启":"Protezione accesso disattivata: si attiva impostando una password","新密码至少 6 位":"La nuova password deve avere almeno 6 caratteri","两次输入的新密码不一致":"Le nuove password non coincidono","提交中…":"Invio in corso…","空目录":"Cartella vuota","正在连接 GitHub…":"Connessione a GitHub…","检查失败":"Controllo non riuscito","连不上 GitHub":"Impossibile raggiungere GitHub","(可稍后重试)":"(puoi riprovare più tardi)","来源":"Origine","升级失败":"Aggiornamento non riuscito","原密码不对":"Password attuale errata","修改失败":"Modifica non riuscita","上传失败":"Caricamento non riuscito","密码已更新, 其它设备需要重新登录":"Password aggiornata, gli altri dispositivi devono riaccedere","仅支持 css/jpg/png/webp":"Solo css/jpg/png/webp","皮肤已上传并应用":"Tema caricato e applicato","文件超过 100MB 上限":"File oltre il limite di 100MB","车机U盘已连接 (已临时断开车机读取, 5分钟无操作自动恢复)":"Chiavetta USB dell'auto collegata (lettura dall'auto sospesa, ripristino automatico dopo 5 minuti di inattività)","已恢复车机导出":"Esportazione dall'auto ripristinata","车机U盘未连接, 请先点「连接车机U盘」":"Chiavetta USB dell'auto non collegata, tocca prima «Collega chiavetta USB auto»","归档里没有可用的片段":"Nessun clip disponibile nell'archivio","请至少选择一路":"Seleziona almeno un canale","已有合成在进行":"Composizione già in corso","合成失败":"Composizione non riuscita","已开始下载":"Download avviato","此浏览器不支持本机合成, 请使用打包下载":"Questo browser non supporta la composizione locale, usa il download in pacchetto","TSL哨兵云盘":"TSL Sentry Drive","合成完成":"Unione completata","路":{"en":"cams","de":"Kam.","fr":"cams","it":"cam","es":"cams","nl":"cam.","ru":"кам.","ja":"カメラ","ko":"카메라"}},"ja":{"品牌":"ブランド","App ID — cli_ 开头":"App ID — cli_ で始まる","App Secret (已保存则留空表示不修改)":"App Secret（保存済みなら空欄で変更なし）","‹ 返回":"‹ 戻る","⏳ 待写入车机U盘:":"⏳ 車載USBへの書き込み待ち:","▶ 轻触开始同步播放":"▶ タップして同期再生を開始","⚙ 个性化":"⚙ カスタマイズ","✅ 已写入:":"✅ 書き込み済み:","上传 CSS 皮肤文件或背景图 (jpg/png/webp)。CSS 中引用图片请用 /skin-media/文件名。":"CSSスキンまたは背景画像（jpg/png/webp）をアップロード。CSS内で画像を参照するときは /skin-media/ファイル名 を使います。","下载":"ダウンロード","下载清晰度":"ダウンロード画質","主题":"テーマ","也推手动保存":"手動保存も通知","仅支持 wav/mp3":"wav/mp3 のみ対応","仅限本人访问":"本人限定アクセス","今天":"今日","位置":"位置","使用中":"使用中","侦测到物体移动":"物体の動きを検知","侦测到碰撞/震动":"衝突・振動を検知","保存失败":"保存に失敗しました","保存设置":"設定を保存","修改密码":"パスワード変更","全选":"すべて選択","全部":"すべて","全部日期":"すべての日付","再输一次新密码":"新しいパスワードを再入力","删除":"削除","刹车":"ブレーキ","刹车占比":"ブレーキ割合","前视":"前方","升级会从 GitHub 及多个镜像并发竞速拉取最新程序, 覆盖本机文件并自动重启服务 (约5秒); 配置、录像、登录信息不受影响。":"更新時はGitHubと複数のミラーから最新版を並行して取得し、本体のファイルを上書きしてサービスを自動再起動します（約5秒）。設定・録画・ログイン情報は影響を受けません。","半透明单行: 时间/位置/车速/挡位/油门/刹车, 基本不挡画面":"半透明の1行：時刻/位置/車速/ギア/アクセル/ブレーキ。映像をほぼ遮りません","单选取原文件直接下载(加水印时走本机合成)；多选合成一个多画面视频。下载/打包按所选清晰度导出(首次需等转码)。":"1つ選択時は元ファイルをそのままダウンロード（ウォーターマーク付きは本機で合成）。複数選択時は1つのマルチ画面動画に合成します。ダウンロードとまとめは選択した画質で書き出します（初回は変換待ち）。","原因":"原因","原画":"オリジナル","发送测试":"テスト送信","叠加行车信息水印":"走行データのウォーターマークを重ねる","右B柱":"右Bピラー","右前翼":"右前フェンダー","右翼子板":"右フェンダー","合成视频":"動画を合成","同步状态":"同期状態","后视":"後方","启用推送":"通知を有効化","哨兵告警":"セントリー警告","哨兵模式触发":"セントリーモード作動","哨兵触发时把时间/位置/触发原因和触发画面推到飞书。默认走自建应用私聊(只有你本人可见)；也可切到群机器人 webhook(群里都能看到)。视频推送只支持私聊。":"セントリー作動時に時刻・位置・原因・トリガー映像をFeishuへ送信します。既定は自建アプリの個人チャット（本人のみ閲覧可）で、グループボットのwebhook（グループ全員が閲覧可）にも切り替えられます。動画通知は個人チャットのみ対応です。","哨兵警觉":"セントリー警戒","回滚到上一版本":"前のバージョンに戻す","天":"日","实时同步中":"リアルタイム同期中","密码":"パスワード","尝试次数过多，请 5 分钟后再试":"試行回数が多すぎます。5分後にもう一度お試しください","展开详细数据 ⌄":"詳細データを開く ⌄","左B柱":"左Bピラー","左前翼":"左前フェンダー","左翼子板":"左フェンダー","已保存":"保存しました","已删除":"削除しました","已加入队列, 归档同步时写入车机U盘":"キューに追加しました。保存同期時に車載USBへ書き込みます","已同步":"同期済み","已是最新":"最新です","延迟推送":"通知の遅延","当前密码":"現在のパスワード","当前版本":"現在のバージョン","恢复车机导出":"車載機のエクスポートを再開","手动保存":"手動保存","打包zip":"zipにまとめる","按喇叭保存":"ホーンで保存","换个日期或点「全部」查看本分类所有事件":"日付を変えるか「すべて」をタップすると、この分類の全イベントを表示します","接收人: 你的 open_id (ou_ 开头) 或飞书登录邮箱":"受信者：あなたの open_id（ou_ で始まる）またはFeishuのログインメール","推送内容：封面卡片（触发那帧图 + 信息，最快）":"通知内容：カバーカード（トリガー時のフレーム＋情報、最速）","推送内容：触发摄像头视频（可回放）":"通知内容：トリガーカメラの動画（再生可）","摄像头":"カメラ","收起详细数据 ⌃":"詳細データを閉じる ⌃","改完本机会自动用新密码重新登录，手机/其它设备上的登录状态立即失效。":"変更後は本機が新しいパスワードで自動再ログインし、スマホや他の端末のログイン状態は即座に無効になります。","敏感信息已明文显示，注意别外发":"機密情報を表示中。外部に送らないでください","敏感信息已隐藏（截图安全）":"機密情報は非表示です（スクショ安全）","新密码 (至少 6 位)":"新しいパスワード（6文字以上）","方向盘角度":"ステアリング角度","日期":"日付","时间":"時刻","昨天":"昨日","暂无归档视频":"保存された動画はありません","暂无皮肤, 使用默认外观":"スキンなし、既定の外観を使用","最新版本":"最新バージョン","有新版本":"新しいバージョンあり","未标注原因":"原因の記録なし","未检查":"未確認","条":"件","查看链接前缀 (可选): http://你的域名:端口":"閲覧リンクの接頭辞（任意）: http://あなたのドメイン:ポート","检查中…":"確認中…","检查更新":"更新を確認","正在上传…":"アップロード中…","正在下载并校验新版本…":"新バージョンをダウンロードして検証中…","正在合成多画面视频":"マルチ画面動画を合成中","活动ID":"イベントID","浅色":"ライト","浏览和管理车机U盘 (特斯拉写入的镜像)。连接后会临时断开车机读取几秒，5 分钟无操作自动恢复。":"車載USB（Teslaが書き込むミラー）を閲覧・管理します。接続すると車載機の読み取りが数秒中断され、5分間操作がないと自動で復帰します。","深色":"ダーク","清空":"クリア","点击行车记录仪图标":"ドラレコアイコンをタップ","片段":"クリップ","用户名":"ユーザー名","用户名或密码不对":"ユーザー名またはパスワードが違います","画面":"映像","界面语言，保存在本机浏览器":"表示言語はこのブラウザに保存されます","登录":"ログイン","登录状态保留":"ログイン状態の保持","盒子归档存储":"ボックス保存領域","确定要退出登录吗？":"ログアウトしますか？","私聊推送 — 只有我本人能看到":"個人チャット通知 — 本人だけが閲覧可","秒 (等片段写完再推)":"秒（クリップ完成後に通知）","秒（从触发前 5 秒开始截）":"秒（トリガー5秒前から記録）","立即升级":"今すぐ更新","群机器人 webhook (仅群推送需要): https://open.feishu.cn/open-apis/bot/v2/hook/...":"グループボットの webhook（グループ通知のみ必要）: https://open.feishu.cn/open-apis/bot/v2/hook/...","群机器人 — 群里所有人都能看到":"グループボット — グループ全員が閲覧可","自动":"自動","行车记录":"ドライブレコーダー","行车记录仪菜单保存":"ドラレコメニューから保存","视频时长":"動画の長さ","视频清晰度：360p（约 1.8MB / 30 秒）":"動画画質：360p（約1.8MB / 30秒）","视频清晰度：480p（约 3MB / 30 秒）":"動画画質：480p（約3MB / 30秒）","视频清晰度：720p（约 5MB / 30 秒）":"動画画質：720p（約5MB / 30秒）","触发原因":"トリガー原因","设为锁车音":"ロック音に設定","设备正在拼接各路画面, 请勿关闭页面":"各カメラの映像を結合しています。ページを閉じないでください","设置":"設定","该筛选下暂无事件":"この条件のイベントはありません","跳转":"移動","车机U盘未连接":"車載USB未接続","车机录制后, 归档同步任务会自动把视频收进来 (镜像需空闲10分钟)":"車載機で録画されると、保存同期が自動で動画を取り込みます（ミラーは10分の待機が必要）","车机要求单个音频 <1MB, 请裁剪后重试":"車載機の制限で1ファイル<1MBです。トリミングして再試行してください","车载U盘存储":"車載USBストレージ","车门拉动":"ドアを引かれた","车门被拉动":"ドアが引かれました","载入中…":"読み込み中…","连接车机U盘":"車載USBに接続","退出登录":"ログアウト","选择日期…":"日付を選択…","选择要导出的画面":"書き出す映像を選択","选择语言":"言語を選択","遭遇袭击":"襲撃を検知","遭遇袭击 (紧急报警)":"襲撃を検知（緊急通報）","锁车音":"ロック音","锁车音必须是 WAV (mp3 只能当喇叭音效)":"ロック音はWAVのみ（mp3はホーン音としてのみ使用可）","锁车音要求 WAV 44.1kHz 16-bit <1MB 1~5秒；LockChime.wav 写入车机U盘根目录，其它 mp3/wav 作为 Boombox 音效写入 Boombox/ 目录。文件在归档同步时写入车机U盘。":"ロック音はWAV 44.1kHz 16-bit <1MB 1〜5秒。LockChime.wav は車載USBのルートに、その他の mp3/wav は Boombox 音效として Boombox/ ディレクトリに書き込みます。ファイルは保存同期時に車載USBへ書き込まれます。","门把手被拉动":"ドアノブが引かれました","＋ 上传文件到当前目录 (任意类型, ≤100MB)":"＋ 現在のフォルダにファイルをアップロード (任意の種類, ≤100MB)","＋ 上传皮肤文件 (css/jpg/png/webp)":"＋ スキンファイルをアップロード (css/jpg/png/webp)","＋ 上传音频 (wav/mp3, <1MB)":"＋ 音声をアップロード (wav/mp3, <1MB)","🌐 语言":"🌐 言語","🎨 网页背景":"🎨 スキン","👁 显示":"👁 表示","📂 文件":"📂 ファイル","🔄 更新":"🔄 アップデート","🔊 锁车语音":"🔊 ロック音","🔑 账号":"🔑 アカウント","🔔 推送":"🔔 通知","🗄 归档区":"🗄 保存領域","🙈 隐藏":"🙈 隠す","🚗 特斯拉哨兵查看器":"🚗 テスラ・セントリービューア","🚗 车机U盘":"🚗 車載USB","归档":"保存領域","待确认":"確認待ち","同步服务未运行":"同期サービスが停止中","路画面":"画面","最近一次":"最新","未启用":"無効","已启用私聊推送, 等下一个哨兵事件":"個人チャット通知を有効にしました。次のセントリーイベントを待機中","已启用, 但接收人/应用凭据未配全":"有効ですが、受信者またはアプリ資格情報が未設定です","读取设置失败":"設定の読み込みに失敗しました","私聊需要 App ID / Secret + 接收人":"個人チャットには App ID / Secret と受信者が必要です","请先填群机器人 webhook":"先にグループボットの webhook を入力してください","保存中…":"保存中…","发送失败":"送信に失敗しました","正在发送测试卡片…":"テストカードを送信中…","当前未开启登录保护, 设置密码后即开启":"現在ログイン保護は無効です。パスワードを設定すると有効になります","新密码至少 6 位":"新しいパスワードは6文字以上","两次输入的新密码不一致":"新しいパスワードが一致しません","提交中…":"送信中…","空目录":"空のフォルダ","正在连接 GitHub…":"GitHub に接続中…","检查失败":"確認に失敗しました","连不上 GitHub":"GitHub に接続できません","(可稍后重试)":"(後で再試行できます)","来源":"ソース","升级失败":"アップデートに失敗しました","原密码不对":"現在のパスワードが違います","修改失败":"変更に失敗しました","上传失败":"アップロードに失敗しました","密码已更新, 其它设备需要重新登录":"パスワードを更新しました。他の端末では再ログインが必要です","仅支持 css/jpg/png/webp":"css/jpg/png/webp のみ対応","皮肤已上传并应用":"スキンをアップロードして適用しました","文件超过 100MB 上限":"ファイルが上限の100MBを超えています","车机U盘已连接 (已临时断开车机读取, 5分钟无操作自动恢复)":"車載USBメモリを接続しました (車載機の読み取りを一時停止中。5分間操作がないと自動復帰)","已恢复车机导出":"車載機のエクスポートを復帰しました","车机U盘未连接, 请先点「连接车机U盘」":"車載USBメモリが未接続です。先に「車載USBメモリに接続」を押してください","归档里没有可用的片段":"保存領域に使用できるクリップがありません","请至少选择一路":"少なくとも1画面を選択してください","已有合成在进行":"合成を実行中です","合成失败":"合成に失敗しました","已开始下载":"ダウンロードを開始しました","此浏览器不支持本机合成, 请使用打包下载":"このブラウザは本機合成に非対応です。まとめてダウンロードしてください","TSL哨兵云盘":"TSL Sentry Drive","合成完成":"合成完了","路":{"en":"cams","de":"Kam.","fr":"cams","it":"cam","es":"cams","nl":"cam.","ru":"кам.","ja":"カメラ","ko":"카메라"}},"ko":{"品牌":"브랜드","App ID — cli_ 开头":"App ID — cli_ 로 시작","App Secret (已保存则留空表示不修改)":"App Secret (저장된 경우 비워두면 변경 안 함)","‹ 返回":"‹ 뒤로","⏳ 待写入车机U盘:":"⏳ 차량 USB 기록 대기:","▶ 轻触开始同步播放":"▶ 눌러서 동기화 재생 시작","⚙ 个性化":"⚙ 개인 설정","✅ 已写入:":"✅ 기록 완료:","上传 CSS 皮肤文件或背景图 (jpg/png/webp)。CSS 中引用图片请用 /skin-media/文件名。":"CSS 스킨이나 배경 이미지(jpg/png/webp)를 업로드하세요. CSS에서 이미지를 참조할 때는 /skin-media/파일명을 사용하세요.","下载":"다운로드","下载清晰度":"다운로드 화질","主题":"테마","也推手动保存":"수동 저장도 알림","仅支持 wav/mp3":"wav/mp3만 지원","仅限本人访问":"본인만 접근 가능","今天":"오늘","位置":"위치","使用中":"사용 중","侦测到物体移动":"물체 움직임 감지","侦测到碰撞/震动":"충돌/진동 감지","保存失败":"저장 실패","保存设置":"설정 저장","修改密码":"비밀번호 변경","全选":"전체 선택","全部":"전체","全部日期":"모든 날짜","再输一次新密码":"새 비밀번호 다시 입력","删除":"삭제","刹车":"브레이크","刹车占比":"브레이크 비율","前视":"전방","升级会从 GitHub 及多个镜像并发竞速拉取最新程序, 覆盖本机文件并自动重启服务 (约5秒); 配置、录像、登录信息不受影响。":"업데이트 시 GitHub와 여러 미러에서 최신 프로그램을 동시에 받아 본체 파일을 덮어쓰고 서비스를 자동 재시작합니다 (약 5초). 설정, 녹화, 로그인 정보는 영향받지 않습니다.","半透明单行: 时间/位置/车速/挡位/油门/刹车, 基本不挡画面":"반투명 한 줄: 시간/위치/속도/기어/액셀/브레이크, 화면을 거의 가리지 않음","单选取原文件直接下载(加水印时走本机合成)；多选合成一个多画面视频。下载/打包按所选清晰度导出(首次需等转码)。":"하나 선택 시 원본 파일을 바로 다운로드(워터마크 시 본체에서 합성), 여러 개 선택 시 하나의 다중 화면 영상으로 합성합니다. 다운로드와 묶기는 선택한 화질로 내보냅니다(처음엔 변환 대기 필요).","原因":"원인","原画":"원본","发送测试":"테스트 전송","叠加行车信息水印":"주행 정보 워터마크 표시","右B柱":"우측 B필러","右前翼":"우측 전면 펜더","右翼子板":"우측 펜더","合成视频":"영상 합성","同步状态":"동기화 상태","后视":"후방","启用推送":"알림 사용","哨兵告警":"센트리 경보","哨兵模式触发":"센트리 모드 작동","哨兵触发时把时间/位置/触发原因和触发画面推到飞书。默认走自建应用私聊(只有你本人可见)；也可切到群机器人 webhook(群里都能看到)。视频推送只支持私聊。":"센트리 작동 시 시간/위치/트리거 원인과 트리거 화면을 Feishu로 보냅니다. 기본은 자체 앱 개인 채팅(본인만 확인 가능)이며, 그룹 봇 webhook(그룹원 모두 확인 가능)으로 전환할 수 있습니다. 영상 알림은 개인 채팅만 지원합니다.","哨兵警觉":"센트리 주의","回滚到上一版本":"이전 버전으로 롤백","天":"일","实时同步中":"실시간 동기화 중","密码":"비밀번호","尝试次数过多，请 5 分钟后再试":"시도 횟수가 너무 많습니다. 5분 후 다시 시도하세요","展开详细数据 ⌄":"상세 데이터 펼치기 ⌄","左B柱":"좌측 B필러","左前翼":"좌측 전면 펜더","左翼子板":"좌측 펜더","已保存":"저장됨","已删除":"삭제됨","已加入队列, 归档同步时写入车机U盘":"대기열에 추가됨, 보관 동기화 시 차량 USB에 기록","已同步":"동기화됨","已是最新":"최신 버전","延迟推送":"알림 지연","当前密码":"현재 비밀번호","当前版本":"현재 버전","恢复车机导出":"차량 내보내기 복구","手动保存":"수동 저장","打包zip":"zip으로 묶기","按喇叭保存":"경적을 눌러 저장","换个日期或点「全部」查看本分类所有事件":"날짜를 바꾸거나 「전체」를 눌러 이 분류의 모든 이벤트를 보세요","接收人: 你的 open_id (ou_ 开头) 或飞书登录邮箱":"수신자: 내 open_id (ou_ 로 시작) 또는 Feishu 로그인 이메일","推送内容：封面卡片（触发那帧图 + 信息，最快）":"알림 내용: 커버 카드 (트리거 순간 이미지 + 정보, 가장 빠름)","推送内容：触发摄像头视频（可回放）":"알림 내용: 트리거 카메라 영상 (재생 가능)","摄像头":"카메라","收起详细数据 ⌃":"상세 데이터 접기 ⌃","改完本机会自动用新密码重新登录，手机/其它设备上的登录状态立即失效。":"변경 후 본체는 새 비밀번호로 자동 재로그인되며, 휴대폰과 다른 기기의 로그인 상태는 즉시 만료됩니다.","敏感信息已明文显示，注意别外发":"민감 정보가 표시됩니다. 외부 유출 주의","敏感信息已隐藏（截图安全）":"민감 정보가 가려졌습니다 (캡처 안전)","新密码 (至少 6 位)":"새 비밀번호 (6자 이상)","方向盘角度":"핸들 각도","日期":"날짜","时间":"시간","昨天":"어제","暂无归档视频":"보관된 영상이 없습니다","暂无皮肤, 使用默认外观":"스킨 없음, 기본 화면 사용","最新版本":"최신 버전","有新版本":"새 버전 있음","未标注原因":"원인 미표시","未检查":"확인 안 함","条":"개","查看链接前缀 (可选): http://你的域名:端口":"조회 링크 접두사 (선택): http://내-도메인:포트","检查中…":"확인 중…","检查更新":"업데이트 확인","正在上传…":"업로드 중…","正在下载并校验新版本…":"새 버전 다운로드 및 검증 중…","正在合成多画面视频":"다중 화면 영상 합성 중","活动ID":"이벤트 ID","浅色":"라이트","浏览和管理车机U盘 (特斯拉写入的镜像)。连接后会临时断开车机读取几秒，5 分钟无操作自动恢复。":"차량 USB(Tesla가 기록하는 미러)를 보고 관리합니다. 연결하면 차량 읽기가 몇 초간 끊기고, 5분간 조작이 없으면 자동 복구됩니다.","深色":"다크","清空":"초기화","点击行车记录仪图标":"블랙박스 아이콘 터치","片段":"클립","用户名":"사용자 이름","用户名或密码不对":"사용자 이름 또는 비밀번호가 틀렸습니다","画面":"화면","界面语言，保存在本机浏览器":"인터페이스 언어는 이 브라우저에 저장됩니다","登录":"로그인","登录状态保留":"로그인 상태 유지","盒子归档存储":"박스 보관 저장공간","确定要退出登录吗？":"로그아웃할까요?","私聊推送 — 只有我本人能看到":"개인 채팅 알림 — 본인만 볼 수 있음","秒 (等片段写完再推)":"초 (클립 저장 후 알림)","秒（从触发前 5 秒开始截）":"초 (트리거 5초 전부터 녹화)","立即升级":"지금 업데이트","群机器人 webhook (仅群推送需要): https://open.feishu.cn/open-apis/bot/v2/hook/...":"그룹 봇 webhook (그룹 알림에만 필요): https://open.feishu.cn/open-apis/bot/v2/hook/...","群机器人 — 群里所有人都能看到":"그룹 봇 — 그룹원 모두 볼 수 있음","自动":"자동","行车记录":"주행 기록","行车记录仪菜单保存":"블랙박스 메뉴에서 저장","视频时长":"영상 길이","视频清晰度：360p（约 1.8MB / 30 秒）":"영상 화질: 360p (약 1.8MB / 30초)","视频清晰度：480p（约 3MB / 30 秒）":"영상 화질: 480p (약 3MB / 30초)","视频清晰度：720p（约 5MB / 30 秒）":"영상 화질: 720p (약 5MB / 30초)","触发原因":"트리거 원인","设为锁车音":"잠금음으로 설정","设备正在拼接各路画面, 请勿关闭页面":"각 화면을 이어 붙이는 중입니다. 페이지를 닫지 마세요","设置":"설정","该筛选下暂无事件":"이 필터에 이벤트가 없습니다","跳转":"이동","车机U盘未连接":"차량 USB 연결 안 됨","车机录制后, 归档同步任务会自动把视频收进来 (镜像需空闲10分钟)":"차량에서 녹화하면 보관 동기화 작업이 자동으로 영상을 가져옵니다 (미러는 10분간 유휴 필요)","车机要求单个音频 <1MB, 请裁剪后重试":"차량 요구사항으로 파일당 <1MB입니다. 잘라서 다시 시도하세요","车载U盘存储":"차량 USB 저장공간","车门拉动":"문 당김","车门被拉动":"문이 당겨졌습니다","载入中…":"불러오는 중…","连接车机U盘":"차량 USB 연결","退出登录":"로그아웃","选择日期…":"날짜 선택…","选择要导出的画面":"내보낼 화면 선택","选择语言":"언어 선택","遭遇袭击":"차량 습격 감지","遭遇袭击 (紧急报警)":"차량 습격 감지 (긴급 경보)","锁车音":"잠금음","锁车音必须是 WAV (mp3 只能当喇叭音效)":"잠금음은 WAV만 가능 (mp3는 경적음으로만 사용)","锁车音要求 WAV 44.1kHz 16-bit <1MB 1~5秒；LockChime.wav 写入车机U盘根目录，其它 mp3/wav 作为 Boombox 音效写入 Boombox/ 目录。文件在归档同步时写入车机U盘。":"잠금음은 WAV 44.1kHz 16-bit <1MB 1~5초가 필요합니다. LockChime.wav는 차량 USB 루트에, 그 외 mp3/wav는 Boombox 음향으로 Boombox/ 폴더에 기록됩니다. 파일은 보관 동기화 시 차량 USB에 기록됩니다.","门把手被拉动":"도어 손잡이가 당겨졌습니다","＋ 上传文件到当前目录 (任意类型, ≤100MB)":"＋ 현재 폴더로 파일 업로드 (모든 형식, ≤100MB)","＋ 上传皮肤文件 (css/jpg/png/webp)":"＋ 스킨 파일 업로드 (css/jpg/png/webp)","＋ 上传音频 (wav/mp3, <1MB)":"＋ 오디오 업로드 (wav/mp3, <1MB)","🌐 语言":"🌐 언어","🎨 网页背景":"🎨 스킨","👁 显示":"👁 표시","📂 文件":"📂 파일","🔄 更新":"🔄 업데이트","🔊 锁车语音":"🔊 잠금 사운드","🔑 账号":"🔑 계정","🔔 推送":"🔔 알림","🗄 归档区":"🗄 보관함","🙈 隐藏":"🙈 숨기기","🚗 特斯拉哨兵查看器":"🚗 테슬라 센트리 뷰어","🚗 车机U盘":"🚗 차량 USB","归档":"보관함","待确认":"확인 대기","同步服务未运行":"동기화 서비스가 실행되지 않음","路画面":"화면","最近一次":"최근","未启用":"사용 안 함","已启用私聊推送, 等下一个哨兵事件":"개인 채팅 알림이 켜졌습니다. 다음 센트리 이벤트를 기다리는 중","已启用, 但接收人/应用凭据未配全":"사용 중이지만 수신자/앱 자격 정보가 모두 설정되지 않았습니다","读取设置失败":"설정을 읽지 못했습니다","私聊需要 App ID / Secret + 接收人":"개인 채팅에는 App ID / Secret 과 수신자가 필요합니다","请先填群机器人 webhook":"먼저 그룹 봇 webhook을 입력하세요","保存中…":"저장 중…","发送失败":"전송 실패","正在发送测试卡片…":"테스트 카드 전송 중…","当前未开启登录保护, 设置密码后即开启":"현재 로그인 보호가 꺼져 있습니다. 비밀번호를 설정하면 켜집니다","新密码至少 6 位":"새 비밀번호는 6자 이상","两次输入的新密码不一致":"새 비밀번호가 일치하지 않습니다","提交中…":"제출 중…","空目录":"빈 폴더","正在连接 GitHub…":"GitHub에 연결 중…","检查失败":"확인 실패","连不上 GitHub":"GitHub에 연결할 수 없음","(可稍后重试)":"(나중에 다시 시도할 수 있습니다)","来源":"출처","升级失败":"업데이트 실패","原密码不对":"현재 비밀번호가 틀렸습니다","修改失败":"변경 실패","上传失败":"업로드 실패","密码已更新, 其它设备需要重新登录":"비밀번호가 변경되었습니다. 다른 기기에서는 다시 로그인해야 합니다","仅支持 css/jpg/png/webp":"css/jpg/png/webp만 지원","皮肤已上传并应用":"스킨을 업로드하고 적용했습니다","文件超过 100MB 上限":"파일이 100MB 한도를 초과했습니다","车机U盘已连接 (已临时断开车机读取, 5分钟无操作自动恢复)":"차량 USB 메모리가 연결되었습니다 (차량 읽기를 일시 중단, 5분간 조작이 없으면 자동 복구)","已恢复车机导出":"차량 내보내기를 복구했습니다","车机U盘未连接, 请先点「连接车机U盘」":"차량 USB 메모리가 연결되지 않았습니다. 먼저 「차량 USB 메모리 연결」을 누르세요","归档里没有可用的片段":"보관함에 사용할 수 있는 클립이 없습니다","请至少选择一路":"화면을 하나 이상 선택하세요","已有合成在进行":"이미 합성 중입니다","合成失败":"합성 실패","已开始下载":"다운로드를 시작했습니다","此浏览器不支持本机合成, 请使用打包下载":"이 브라우저는 본체 합성을 지원하지 않습니다. 묶음 다운로드를 사용하세요","TSL哨兵云盘":"TSL Sentry Drive","合成完成":"합성 완료","路":{"en":"cams","de":"Kam.","fr":"cams","it":"cam","es":"cams","nl":"cam.","ru":"кам.","ja":"カメラ","ko":"카메라"}},"nl":{"品牌":"Merk","App ID — cli_ 开头":"App ID — begint met cli_","App Secret (已保存则留空表示不修改)":"App Secret (leeg laten om ongewijzigd te houden)","‹ 返回":"‹ Terug","⏳ 待写入车机U盘:":"⏳ Nog naar de USB van de auto te schrijven:","▶ 轻触开始同步播放":"▶ Tik om synchroon af te spelen","⚙ 个性化":"⚙ Personalisatie","✅ 已写入:":"✅ Geschreven:","上传 CSS 皮肤文件或背景图 (jpg/png/webp)。CSS 中引用图片请用 /skin-media/文件名。":"Upload een CSS-skinbestand of achtergrondafbeelding (jpg/png/webp). Verwijs naar afbeeldingen in CSS via /skin-media/bestandsnaam.","下载":"Downloaden","下载清晰度":"Downloadkwaliteit","主题":"Thema","也推手动保存":"Ook handmatige opnames","仅支持 wav/mp3":"Alleen wav/mp3","仅限本人访问":"Alleen toegankelijk voor jou","今天":"Vandaag","位置":"Locatie","使用中":"In gebruik","侦测到物体移动":"Beweging gedetecteerd","侦测到碰撞/震动":"Botsing/schok gedetecteerd","保存失败":"Opslaan mislukt","保存设置":"Instellingen opslaan","修改密码":"Wachtwoord wijzigen","全选":"Alles selecteren","全部":"Alles","全部日期":"Alle datums","再输一次新密码":"Herhaal het nieuwe wachtwoord","删除":"Verwijderen","刹车":"Rem","刹车占比":"Rempercentage","前视":"Voor","升级会从 GitHub 及多个镜像并发竞速拉取最新程序, 覆盖本机文件并自动重启服务 (约5秒); 配置、录像、登录信息不受影响。":"De update haalt de nieuwste versie parallel op van GitHub en meerdere mirrors, overschrijft de lokale bestanden en herstart de service (circa 5 s); instellingen, opnames en inloggegevens blijven behouden.","半透明单行: 时间/位置/车速/挡位/油门/刹车, 基本不挡画面":"Eén semi-transparante regel: tijd/locatie/snelheid/versnelling/gas/rem, nauwelijks zichtbaar over het beeld","单选取原文件直接下载(加水印时走本机合成)；多选合成一个多画面视频。下载/打包按所选清晰度导出(首次需等转码)。":"Bij één selectie download je het originele bestand (met watermerk wordt het lokaal samengesteld); bij meerdere selecties wordt één multi-beeldvideo gemaakt. Downloaden en zippen gebeurt in de gekozen kwaliteit (de eerste keer moet er worden getranscodeerd).","原因":"Reden","原画":"Origineel","发送测试":"Test verzenden","叠加行车信息水印":"Rijgegevens als watermerk toevoegen","右B柱":"B-stijl rechts","右前翼":"Voorspatbord rechts","右翼子板":"Spatbord rechts","合成视频":"Video samenvoegen","同步状态":"Synchronisatiestatus","后视":"Achter","启用推送":"Meldingen inschakelen","哨兵告警":"Sentry-meldingen","哨兵模式触发":"Sentry geactiveerd","哨兵触发时把时间/位置/触发原因和触发画面推到飞书。默认走自建应用私聊(只有你本人可见)；也可切到群机器人 webhook(群里都能看到)。视频推送只支持私聊。":"Bij een Sentry-trigger worden tijd/locatie/oorzaak en het triggerbeeld naar Feishu gestuurd. Standaard via de eigen app in privé (alleen jij ziet het); je kunt ook de webhook van een groepsbot gebruiken (iedereen in de groep ziet het). Video-push kan alleen privé.","哨兵警觉":"Sentry-alert","回滚到上一版本":"Terug naar vorige versie","天":"dagen","实时同步中":"Live synchroniseren","密码":"Wachtwoord","尝试次数过多，请 5 分钟后再试":"Te veel pogingen, probeer het over 5 minuten","展开详细数据 ⌄":"Details tonen ⌄","左B柱":"B-stijl links","左前翼":"Voorspatbord links","左翼子板":"Spatbord links","已保存":"Opgeslagen","已删除":"Verwijderd","已加入队列, 归档同步时写入车机U盘":"In de wachtrij, wordt bij de archiefsynchronisatie naar de USB van de auto geschreven","已同步":"Gesynchroniseerd","已是最新":"Al up-to-date","延迟推送":"Vertraagde melding","当前密码":"Huidig wachtwoord","当前版本":"Huidige versie","恢复车机导出":"Toegang auto herstellen","手动保存":"Handmatige opnames","打包zip":"zip maken","按喇叭保存":"Opgeslagen met claxon","换个日期或点「全部」查看本分类所有事件":"Kies een andere datum of tik op 'Alles' om alle gebeurtenissen van deze categorie te zien","接收人: 你的 open_id (ou_ 开头) 或飞书登录邮箱":"Ontvanger: je open_id (begint met ou_) of je Feishu-inlogmail","推送内容：封面卡片（触发那帧图 + 信息，最快）":"Inhoud: omslagkaart (beeld van de trigger + info, het snelst)","推送内容：触发摄像头视频（可回放）":"Inhoud: video van de camera die triggerde (afspeelbaar)","摄像头":"Camera","收起详细数据 ⌃":"Details verbergen ⌃","改完本机会自动用新密码重新登录，手机/其它设备上的登录状态立即失效。":"Na de wijziging logt dit apparaat automatisch opnieuw in met het nieuwe wachtwoord; sessies op je telefoon en andere apparaten vervallen direct.","敏感信息已明文显示，注意别外发":"Gevoelige gegevens zichtbaar, deel ze niet","敏感信息已隐藏（截图安全）":"Gevoelige gegevens verborgen (veilig voor screenshots)","新密码 (至少 6 位)":"Nieuw wachtwoord (minimaal 6 tekens)","方向盘角度":"Stuurhoek","日期":"Datum","时间":"Tijd","昨天":"Gisteren","暂无归档视频":"Geen gearchiveerde video's","暂无皮肤, 使用默认外观":"Geen skins, standaarduiterlijk","最新版本":"Nieuwste versie","有新版本":"Nieuwe versie beschikbaar","未标注原因":"Geen reden opgegeven","未检查":"Niet gecontroleerd","条":"clips","查看链接前缀 (可选): http://你的域名:端口":"Voorvoegsel weergavelink (optioneel): http://jouwdomein:poort","检查中…":"Controleren…","检查更新":"Controleren op updates","正在上传…":"Uploaden…","正在下载并校验新版本…":"Nieuwe versie downloaden en verifiëren…","正在合成多画面视频":"Multi-beeldvideo wordt gemaakt","活动ID":"Gebeurtenis-ID","浅色":"Licht","浏览和管理车机U盘 (特斯拉写入的镜像)。连接后会临时断开车机读取几秒，5 分钟无操作自动恢复。":"Bekijk en beheer de USB van de auto (de kopie die Tesla schrijft). Bij verbinden verliest de auto enkele seconden de toegang; na 5 minuten zonder activiteit wordt dit hersteld.","深色":"Donker","清空":"Selectie opheffen","点击行车记录仪图标":"Dashcam-pictogram aangetikt","片段":"Clips","用户名":"Gebruikersnaam","用户名或密码不对":"Gebruikersnaam of wachtwoord onjuist","画面":"Beelden","界面语言，保存在本机浏览器":"Taal van de interface, opgeslagen in deze browser","登录":"Inloggen","登录状态保留":"Ingelogd blijven","盒子归档存储":"Archiefopslag box","确定要退出登录吗？":"Weet je zeker dat je wilt uitloggen?","私聊推送 — 只有我本人能看到":"Privébericht — alleen jij kunt het zien","秒 (等片段写完再推)":"seconden (wacht tot de clips zijn geschreven)","秒（从触发前 5 秒开始截）":"seconden (vanaf 5 s voor de trigger)","立即升级":"Nu bijwerken","群机器人 webhook (仅群推送需要): https://open.feishu.cn/open-apis/bot/v2/hook/...":"webhook van groepsbot (alleen nodig voor groepspush): https://open.feishu.cn/open-apis/bot/v2/hook/...","群机器人 — 群里所有人都能看到":"Groepsbot — iedereen in de groep kan het zien","自动":"Automatisch","行车记录":"Dashcam","行车记录仪菜单保存":"Opgeslagen via Dashcam-menu","视频时长":"Duur van de video","视频清晰度：360p（约 1.8MB / 30 秒）":"Videokwaliteit: 360p (circa 1.8MB / 30 s)","视频清晰度：480p（约 3MB / 30 秒）":"Videokwaliteit: 480p (circa 3MB / 30 s)","视频清晰度：720p（约 5MB / 30 秒）":"Videokwaliteit: 720p (circa 5MB / 30 s)","触发原因":"Oorzaak activatie","设为锁车音":"Instellen als vergrendelgeluid","设备正在拼接各路画面, 请勿关闭页面":"Het apparaat voegt de beelden samen, sluit de pagina niet","设置":"Instellingen","该筛选下暂无事件":"Geen gebeurtenissen met dit filter","跳转":"Gaan","车机U盘未连接":"USB van de auto niet verbonden","车机录制后, 归档同步任务会自动把视频收进来 (镜像需空闲10分钟)":"Na opname in de auto neemt de archiefsynchronisatie de video's automatisch over (de mirror moet 10 minuten inactief zijn)","车机要求单个音频 <1MB, 请裁剪后重试":"De auto vereist audio <1MB, knip het bestand en probeer opnieuw","车载U盘存储":"USB-opslag auto","车门拉动":"Portier geforceerd","车门被拉动":"Portier opengetrokken","载入中…":"Laden…","连接车机U盘":"USB van de auto verbinden","退出登录":"Uitloggen","选择日期…":"Kies datum…","选择要导出的画面":"Kies de beelden om te exporteren","选择语言":"Taal kiezen","遭遇袭击":"Aanval","遭遇袭击 (紧急报警)":"Aanval (noodalarm)","锁车音":"Vergrendelgeluid","锁车音必须是 WAV (mp3 只能当喇叭音效)":"Vergrendelgeluid moet WAV zijn (mp3 alleen als claxongeluid)","锁车音要求 WAV 44.1kHz 16-bit <1MB 1~5秒；LockChime.wav 写入车机U盘根目录，其它 mp3/wav 作为 Boombox 音效写入 Boombox/ 目录。文件在归档同步时写入车机U盘。":"Vergrendelgeluid vereist WAV 44.1kHz 16-bit <1MB 1~5 s; LockChime.wav wordt in de hoofdmap van de USB van de auto gezet, overige mp3/wav als Boombox-geluiden in de map Boombox/. Bestanden worden bij de archiefsynchronisatie naar de USB van de auto geschreven.","门把手被拉动":"Deurgreep opengetrokken","＋ 上传文件到当前目录 (任意类型, ≤100MB)":"＋ Bestand uploaden naar huidige map (elk type, ≤100MB)","＋ 上传皮肤文件 (css/jpg/png/webp)":"＋ Skinbestand uploaden (css/jpg/png/webp)","＋ 上传音频 (wav/mp3, <1MB)":"＋ Audio uploaden (wav/mp3, <1MB)","🌐 语言":"🌐 Taal","🎨 网页背景":"🎨 Uiterlijk","👁 显示":"👁 Tonen","📂 文件":"📂 Bestanden","🔄 更新":"🔄 Updates","🔊 锁车语音":"🔊 Vergrendelgeluid","🔑 账号":"🔑 Account","🔔 推送":"🔔 Meldingen","🗄 归档区":"🗄 Archief","🙈 隐藏":"🙈 Verbergen","🚗 特斯拉哨兵查看器":"🚗 TSL Sentry-viewer","🚗 车机U盘":"🚗 USB van de auto","归档":"Archief","待确认":"Te bevestigen","同步服务未运行":"Synchronisatieservice niet actief","路画面":"Kanaalbeeld","最近一次":"Laatste keer","未启用":"Niet ingeschakeld","已启用私聊推送, 等下一个哨兵事件":"Privéberichten ingeschakeld, wacht op de volgende Sentinelle-gebeurtenis","已启用, 但接收人/应用凭据未配全":"Ingeschakeld, maar ontvangers/app-referenties ontbreken","读取设置失败":"Instellingen lezen mislukt","私聊需要 App ID / Secret + 接收人":"Privéberichten vereisen App ID / Secret + ontvanger","请先填群机器人 webhook":"Vul eerst de webhook van de groepsbot in","保存中…":"Opslaan…","发送失败":"Verzenden mislukt","正在发送测试卡片…":"Testkaart wordt verzonden…","当前未开启登录保护, 设置密码后即开启":"Toegangsbeveiliging uit: wordt ingeschakeld zodra je een wachtwoord instelt","新密码至少 6 位":"Nieuw wachtwoord moet minstens 6 tekens hebben","两次输入的新密码不一致":"De nieuwe wachtwoorden komen niet overeen","提交中…":"Bezig met verzenden…","空目录":"Lege map","正在连接 GitHub…":"Verbinden met GitHub…","检查失败":"Controle mislukt","连不上 GitHub":"Kan geen verbinding maken met GitHub","(可稍后重试)":"(probeer het later opnieuw)","来源":"Bron","升级失败":"Upgraden mislukt","原密码不对":"Huidig wachtwoord onjuist","修改失败":"Wijzigen mislukt","上传失败":"Uploaden mislukt","密码已更新, 其它设备需要重新登录":"Wachtwoord bijgewerkt, andere apparaten moeten opnieuw inloggen","仅支持 css/jpg/png/webp":"Alleen css/jpg/png/webp","皮肤已上传并应用":"Thema geüpload en toegepast","文件超过 100MB 上限":"Bestand groter dan de limiet van 100MB","车机U盘已连接 (已临时断开车机读取, 5分钟无操作自动恢复)":"USB-stick van de auto verbonden (lezen door de auto tijdelijk gestopt, automatisch hersteld na 5 minuten inactiviteit)","已恢复车机导出":"Export vanaf de auto hersteld","车机U盘未连接, 请先点「连接车机U盘」":"USB-stick van de auto niet verbonden, tik eerst op 'USB-stick auto verbinden'","归档里没有可用的片段":"Geen bruikbare clips in het archief","请至少选择一路":"Selecteer minstens één kanaal","已有合成在进行":"Er loopt al een samenvoeging","合成失败":"Samenvoegen mislukt","已开始下载":"Download gestart","此浏览器不支持本机合成, 请使用打包下载":"Deze browser ondersteunt lokaal samenvoegen niet, gebruik de download als pakket","TSL哨兵云盘":"TSL Sentry Drive","合成完成":"Samenvoegen klaar","路":{"en":"cams","de":"Kam.","fr":"cams","it":"cam","es":"cams","nl":"cam.","ru":"кам.","ja":"カメラ","ko":"카메라"}},"ru":{"品牌":"Бренд","App ID — cli_ 开头":"App ID — начинается с cli_","App Secret (已保存则留空表示不修改)":"App Secret (оставьте пустым, чтобы не менять)","‹ 返回":"‹ Назад","⏳ 待写入车机U盘:":"⏳ Ожидают записи на USB авто:","▶ 轻触开始同步播放":"▶ Коснитесь для синхронного воспроизведения","⚙ 个性化":"⚙ Персонализация","✅ 已写入:":"✅ Записано:","上传 CSS 皮肤文件或背景图 (jpg/png/webp)。CSS 中引用图片请用 /skin-media/文件名。":"Загрузите CSS-скин или фоновое изображение (jpg/png/webp). В CSS ссылайтесь на картинки как /skin-media/имя файла.","下载":"Скачать","下载清晰度":"Качество скачивания","主题":"Тема","也推手动保存":"И ручные сохранения","仅支持 wav/mp3":"Поддерживается только wav/mp3","仅限本人访问":"Доступ только для владельца","今天":"Сегодня","位置":"Место","使用中":"Используется","侦测到物体移动":"Обнаружено движение объекта","侦测到碰撞/震动":"Обнаружен удар или вибрация","保存失败":"Не удалось сохранить","保存设置":"Сохранить","修改密码":"Сменить пароль","全选":"Выбрать все","全部":"Все","全部日期":"Все даты","再输一次新密码":"Повторите новый пароль","删除":"Удалить","刹车":"Тормоз","刹车占比":"Доля торможения","前视":"Передняя","升级会从 GitHub 及多个镜像并发竞速拉取最新程序, 覆盖本机文件并自动重启服务 (约5秒); 配置、录像、登录信息不受影响。":"При обновлении последняя версия скачивается с GitHub и нескольких зеркал одновременно, файлы на устройстве заменяются, сервис перезапускается (около 5 с); настройки, записи и данные входа не затрагиваются.","半透明单行: 时间/位置/车速/挡位/油门/刹车, 基本不挡画面":"Полупрозрачная строка: время/место/скорость/передача/газ/тормоз, почти не закрывает кадр","单选取原文件直接下载(加水印时走本机合成)；多选合成一个多画面视频。下载/打包按所选清晰度导出(首次需等转码)。":"Один файл скачивается как оригинал (с водяным знаком — сборка на устройстве); несколько — в одно многокамерное видео. Скачивание и архив идут в выбранном качестве (в первый раз нужно дождаться перекодирования).","原因":"Причина","原画":"Оригинал","发送测试":"Отправить тест","叠加行车信息水印":"Добавить водяной знак с данными","右B柱":"Правая стойка B","右前翼":"Правое переднее крыло","右翼子板":"Правое крыло","合成视频":"Объединить в видео","同步状态":"Статус синхронизации","后视":"Задняя","启用推送":"Включить уведомления","哨兵告警":"Оповещения Sentry","哨兵模式触发":"Сработал режим Sentry","哨兵触发时把时间/位置/触发原因和触发画面推到飞书。默认走自建应用私聊(只有你本人可见)；也可切到群机器人 webhook(群里都能看到)。视频推送只支持私聊。":"При срабатывании Sentry время, место, причина и кадр отправляются в Feishu. По умолчанию — личные сообщения приложения (видите только вы); можно переключиться на webhook бота чата (видят все в чате). Видео отправляется только в личные сообщения.","哨兵警觉":"Внимание Sentry","回滚到上一版本":"Откатить к прошлой версии","天":"дн.","实时同步中":"Синхронизация в реальном времени","密码":"Пароль","尝试次数过多，请 5 分钟后再试":"Слишком много попыток, повторите через 5 минут","展开详细数据 ⌄":"Развернуть данные ⌄","左B柱":"Левая стойка B","左前翼":"Левое переднее крыло","左翼子板":"Левое крыло","已保存":"Сохранено","已删除":"Удалено","已加入队列, 归档同步时写入车机U盘":"Добавлено в очередь, запись на USB авто при синхронизации","已同步":"Синхронизировано","已是最新":"Актуальная версия","延迟推送":"Задержка отправки","当前密码":"Текущий пароль","当前版本":"Текущая версия","恢复车机导出":"Вернуть доступ авто к USB","手动保存":"Сохранено вручную","打包zip":"Упаковать в zip","按喇叭保存":"Сохранение сигналом","换个日期或点「全部」查看本分类所有事件":"Смените дату или нажмите «Все», чтобы увидеть все события категории","接收人: 你的 open_id (ou_ 开头) 或飞书登录邮箱":"Получатель: ваш open_id (начинается с ou_) или почта входа Feishu","推送内容：封面卡片（触发那帧图 + 信息，最快）":"Содержание: карточка (кадр срабатывания + данные, быстрее всего)","推送内容：触发摄像头视频（可回放）":"Содержание: видео с камеры (с просмотром)","摄像头":"Камера","收起详细数据 ⌃":"Свернуть данные ⌃","改完本机会自动用新密码重新登录，手机/其它设备上的登录状态立即失效。":"После изменения устройство автоматически войдёт с новым паролем, а сеансы на телефоне и других устройствах сразу завершатся.","敏感信息已明文显示，注意别外发":"Чувствительные данные открыты — не пересылайте","敏感信息已隐藏（截图安全）":"Чувствительные данные скрыты (безопасно для скриншотов)","新密码 (至少 6 位)":"Новый пароль (минимум 6 символов)","方向盘角度":"Угол руля","日期":"Дата","时间":"Время","昨天":"Вчера","暂无归档视频":"Архивных видео нет","暂无皮肤, 使用默认外观":"Скинов нет, используется стандартный вид","最新版本":"Последняя версия","有新版本":"Есть обновление","未标注原因":"Причина не указана","未检查":"Не проверено","条":"шт.","查看链接前缀 (可选): http://你的域名:端口":"Префикс ссылки (необязательно): http://ваш-домен:порт","检查中…":"Проверка…","检查更新":"Проверить обновления","正在上传…":"Идёт загрузка…","正在下载并校验新版本…":"Загрузка и проверка новой версии…","正在合成多画面视频":"Идёт сборка многокамерного видео","活动ID":"ID события","浅色":"Светлая","浏览和管理车机U盘 (特斯拉写入的镜像)。连接后会临时断开车机读取几秒，5 分钟无操作自动恢复。":"Просмотр USB авто (зеркало, куда пишет Tesla). При подключении чтение в авто прерывается на несколько секунд, через 5 минут без действий доступ восстанавливается.","深色":"Тёмная","清空":"Очистить","点击行车记录仪图标":"Нажата иконка регистратора","片段":"Фрагментов","用户名":"Имя пользователя","用户名或密码不对":"Неверное имя пользователя или пароль","画面":"Камер","界面语言，保存在本机浏览器":"Язык интерфейса, хранится в этом браузере","登录":"Войти","登录状态保留":"Сеанс сохраняется","盒子归档存储":"Архив на боксе","确定要退出登录吗？":"Выйти из аккаунта?","私聊推送 — 只有我本人能看到":"Личные сообщения — видите только вы","秒 (等片段写完再推)":"с (сначала запись клипа, затем отправка)","秒（从触发前 5 秒开始截）":"с (запись начинается за 5 с до срабатывания)","立即升级":"Обновить сейчас","群机器人 webhook (仅群推送需要): https://open.feishu.cn/open-apis/bot/v2/hook/...":"webhook бота чата (только для группы): https://open.feishu.cn/open-apis/bot/v2/hook/...","群机器人 — 群里所有人都能看到":"Бот в чате — видят все участники","自动":"Авто","行车记录":"Дорожные записи","行车记录仪菜单保存":"Сохранение через меню регистратора","视频时长":"Длительность видео","视频清晰度：360p（约 1.8MB / 30 秒）":"Качество видео: 360p (около 1.8MB / 30 с)","视频清晰度：480p（约 3MB / 30 秒）":"Качество видео: 480p (около 3MB / 30 с)","视频清晰度：720p（约 5MB / 30 秒）":"Качество видео: 720p (около 5MB / 30 с)","触发原因":"Причина срабатывания","设为锁车音":"Сделать звуком закрытия","设备正在拼接各路画面, 请勿关闭页面":"Устройство склеивает камеры, не закрывайте страницу","设置":"Настройки","该筛选下暂无事件":"По этому фильтру событий нет","跳转":"Перейти","车机U盘未连接":"USB авто не подключён","车机录制后, 归档同步任务会自动把视频收进来 (镜像需空闲10分钟)":"После записи в авто задача синхронизации сама заберёт видео (зеркалу нужно 10 минут простоя)","车机要求单个音频 <1MB, 请裁剪后重试":"Авто требует файл <1MB, обрежьте и повторите","车载U盘存储":"Хранилище USB в авто","车门拉动":"Дёргание двери","车门被拉动":"Дверь дёрнули","载入中…":"Загрузка…","连接车机U盘":"Подключить USB авто","退出登录":"Выйти","选择日期…":"Выбрать дату…","选择要导出的画面":"Выберите камеры для экспорта","选择语言":"Выбор языка","遭遇袭击":"Нападение на авто","遭遇袭击 (紧急报警)":"Нападение на авто (тревога)","锁车音":"Звук закрытия","锁车音必须是 WAV (mp3 只能当喇叭音效)":"Звук закрытия должен быть WAV (mp3 — только для Boombox)","锁车音要求 WAV 44.1kHz 16-bit <1MB 1~5秒；LockChime.wav 写入车机U盘根目录，其它 mp3/wav 作为 Boombox 音效写入 Boombox/ 目录。文件在归档同步时写入车机U盘。":"Звук закрытия: WAV 44.1kHz 16-bit <1MB 1–5 с; LockChime.wav записывается в корень USB авто, остальные mp3/wav — как звуки Boombox в папку Boombox/. Файлы записываются на USB авто при синхронизации архива.","门把手被拉动":"Дёрнули ручку двери","＋ 上传文件到当前目录 (任意类型, ≤100MB)":"＋ Загрузить файл в текущую папку (любой тип, ≤100MB)","＋ 上传皮肤文件 (css/jpg/png/webp)":"＋ Загрузить файл скина (css/jpg/png/webp)","＋ 上传音频 (wav/mp3, <1MB)":"＋ Загрузить аудио (wav/mp3, <1MB)","🌐 语言":"🌐 Язык","🎨 网页背景":"🎨 Оформление","👁 显示":"👁 Показать","📂 文件":"📂 Файлы","🔄 更新":"🔄 Обновление","🔊 锁车语音":"🔊 Звук закрытия","🔑 账号":"🔑 Аккаунт","🔔 推送":"🔔 Уведомления","🗄 归档区":"🗄 Архив","🙈 隐藏":"🙈 Скрыть","🚗 特斯拉哨兵查看器":"🚗 Просмотр записей TSL Sentry","🚗 车机U盘":"🚗 USB в авто","归档":"Архив","待确认":"Ожидает подтверждения","同步服务未运行":"Служба синхронизации не запущена","路画面":"Камер","最近一次":"Последний раз","未启用":"Не включено","已启用私聊推送, 等下一个哨兵事件":"Личные уведомления включены, ждём следующее событие Sentry","已启用, 但接收人/应用凭据未配全":"Включено, но получатель или данные приложения заполнены не полностью","读取设置失败":"Не удалось прочитать настройки","私聊需要 App ID / Secret + 接收人":"Для личных сообщений нужны App ID / Secret и получатель","请先填群机器人 webhook":"Сначала укажите webhook бота чата","保存中…":"Сохранение…","发送失败":"Не удалось отправить","正在发送测试卡片…":"Отправка тестовой карточки…","当前未开启登录保护, 设置密码后即开启":"Защита входа выключена, включится после установки пароля","新密码至少 6 位":"Новый пароль — минимум 6 символов","两次输入的新密码不一致":"Новые пароли не совпадают","提交中…":"Отправка…","空目录":"Пустая папка","正在连接 GitHub…":"Подключение к GitHub…","检查失败":"Проверка не удалась","连不上 GitHub":"Нет связи с GitHub","(可稍后重试)":"(можно повторить позже)","来源":"Источник","升级失败":"Не удалось обновить","原密码不对":"Неверный текущий пароль","修改失败":"Не удалось изменить","上传失败":"Не удалось загрузить","密码已更新, 其它设备需要重新登录":"Пароль обновлён, на других устройствах нужен повторный вход","仅支持 css/jpg/png/webp":"Только css/jpg/png/webp","皮肤已上传并应用":"Скин загружен и применён","文件超过 100MB 上限":"Файл больше лимита 100MB","车机U盘已连接 (已临时断开车机读取, 5分钟无操作自动恢复)":"USB-накопитель авто подключён (чтение в авто временно отключено, через 5 минут без действий доступ восстановится)","已恢复车机导出":"Доступ авто к USB восстановлен","车机U盘未连接, 请先点「连接车机U盘」":"USB-накопитель авто не подключён, сначала нажмите «Подключить USB авто»","归档里没有可用的片段":"В архиве нет доступных фрагментов","请至少选择一路":"Выберите хотя бы одну камеру","已有合成在进行":"Сборка уже идёт","合成失败":"Не удалось собрать","已开始下载":"Загрузка начата","此浏览器不支持本机合成, 请使用打包下载":"Браузер не поддерживает сборку на устройстве, используйте скачивание архивом","TSL哨兵云盘":"TSL Sentry Drive","合成完成":"Готово","路":{"en":"cams","de":"Kam.","fr":"cams","it":"cam","es":"cams","nl":"cam.","ru":"кам.","ja":"カメラ","ko":"카메라"}}}

# 图标改成内联 SVG 后, 按钮/标题文字不再带 emoji 前缀 ("🔊 锁车语音" → "锁车语音")。
# 这里给旧键补一份无前缀的同义键, 否则非中文界面会回落到中文; 旧键保留, 兼容仍带 emoji 的文案
_ICON_PREFIX = ("🚗", "🌗", "⚙", "📂", "🔊", "🚙", "🔔", "🔑", "🌐", "🎨", "🔄", "🗄", "🗑", "📦", "📋", "✏️", "👁", "🙈", "🔗")
for _m in LANG_TABLE.values():
    for _k, _v in list(_m.items()):
        for _e in _ICON_PREFIX:
            if _k.startswith(_e + " "):
                _v2 = _v
                for _e2 in _ICON_PREFIX:      # 译文里的 emoji 前缀也一起去掉, 否则会出现「SVG 图标 + emoji」
                    if _v2.startswith(_e2 + " "):
                        _v2 = _v2[len(_e2) + 1:]
                        break
                _m.setdefault(_k[len(_e) + 1:], _v2)
                break


def tr(s, lang="en"):
    """把中文 UI 文案翻成 lang (查不到回落到英文, 再回落到原文)"""
    if not s or lang == "zh":
        return s
    m = LANG_TABLE.get(lang) or {}
    return m.get(s) or (LANG_TABLE.get("en") or {}).get(s) or s

def lang_from_accept(hdr, default="zh"):
    """从 Accept-Language 里挑一个我们支持的语言"""
    codes = [c for c, _ in LANG_NAMES]
    for part in (hdr or "").split(","):
        tag = part.split(";")[0].strip().lower()
        if not tag:
            continue
        if tag in codes:
            return tag
        two = tag.split("-")[0]
        if two in codes:
            return two
    return default

CAT_NAMES = {"SentryClips": "哨兵告警", "SavedClips": "手动保存", "RecentClips": "行车记录"}
# 注入页面用的 JSON (预生成, 避免每次请求都序列化)
FAN_I18N = {
    "en": {"风扇设置": "Fan", "自动温控": "Auto (temp)", "手动定速": "Manual speed", "风扇转速": "Fan speed", "当前温度": "Current temp", "当前占空比": "Current duty", "保存风扇设置": "Save fan settings", "自动模式按温度调速: 45°C 以下停转, 75°C 全速; 手动模式立即生效": "Auto follows temperature: off below 45°C, full at 75°C; manual applies instantly", "风扇不可用: 未启用 overlay 或温控服务未运行": "Fan unavailable: overlay not enabled or control service not running", "读取风扇状态失败": "Failed to read fan state", "风扇设置已保存, 立即生效": "Fan settings saved, applied instantly"},
    "de": {"风扇设置": "Lüfter", "自动温控": "Automatik (Temperatur)", "手动定速": "Manuelle Drehzahl", "风扇转速": "Lüfterdrehzahl", "当前温度": "Aktuelle Temperatur", "当前占空比": "Aktueller Tastgrad", "保存风扇设置": "Lüftereinstellungen speichern", "自动模式按温度调速: 45°C 以下停转, 75°C 全速; 手动模式立即生效": "Automatik nach Temperatur: aus unter 45°C, voll bei 75°C; manuell sofort wirksam", "风扇不可用: 未启用 overlay 或温控服务未运行": "Lüfter nicht verfügbar: Overlay nicht aktiv oder Dienst läuft nicht", "读取风扇状态失败": "Lüfterstatus konnte nicht gelesen werden", "风扇设置已保存, 立即生效": "Lüftereinstellungen gespeichert, sofort wirksam"},
    "fr": {"风扇设置": "Ventilateur", "自动温控": "Auto (température)", "手动定速": "Vitesse manuelle", "风扇转速": "Vitesse du ventilateur", "当前温度": "Température actuelle", "当前占空比": "Rapport cyclique actuel", "保存风扇设置": "Enregistrer les réglages du ventilateur", "自动模式按温度调速: 45°C 以下停转, 75°C 全速; 手动模式立即生效": "Auto selon la température : arrêt sous 45°C, plein à 75°C ; manuel immédiat", "风扇不可用: 未启用 overlay 或温控服务未运行": "Ventilateur indisponible : overlay non activé ou service arrêté", "读取风扇状态失败": "Échec de lecture de l'état du ventilateur", "风扇设置已保存, 立即生效": "Réglages du ventilateur enregistrés, appliqués immédiatement"},
    "it": {"风扇设置": "Ventola", "自动温控": "Auto (temperatura)", "手动定速": "Velocità manuale", "风扇转速": "Velocità ventola", "当前温度": "Temperatura attuale", "当前占空比": "Duty cycle attuale", "保存风扇设置": "Salva impostazioni ventola", "自动模式按温度调速: 45°C 以下停转, 75°C 全速; 手动模式立即生效": "Auto in base alla temperatura: spenta sotto 45°C, massima a 75°C; manuale immediato", "风扇不可用: 未启用 overlay 或温控服务未运行": "Ventola non disponibile: overlay non attivo o servizio non in esecuzione", "读取风扇状态失败": "Lettura stato ventola non riuscita", "风扇设置已保存, 立即生效": "Impostazioni ventola salvate, applicate subito"},
    "es": {"风扇设置": "Ventilador", "自动温控": "Auto (temperatura)", "手动定速": "Velocidad manual", "风扇转速": "Velocidad del ventilador", "当前温度": "Temperatura actual", "当前占空比": "Ciclo de trabajo actual", "保存风扇设置": "Guardar ajustes del ventilador", "自动模式按温度调速: 45°C 以下停转, 75°C 全速; 手动模式立即生效": "Auto según temperatura: apagado por debajo de 45°C, máximo a 75°C; manual inmediato", "风扇不可用: 未启用 overlay 或温控服务未运行": "Ventilador no disponible: overlay no activado o servicio detenido", "读取风扇状态失败": "Error al leer el estado del ventilador", "风扇设置已保存, 立即生效": "Ajustes del ventilador guardados, aplicados al instante"},
    "nl": {"风扇设置": "Ventilator", "自动温控": "Auto (temperatuur)", "手动定速": "Handmatige snelheid", "风扇转速": "Ventilatorsnelheid", "当前温度": "Huidige temperatuur", "当前占空比": "Huidige duty-cycle", "保存风扇设置": "Ventilatorinstellingen opslaan", "自动模式按温度调速: 45°C 以下停转, 75°C 全速; 手动模式立即生效": "Auto op temperatuur: uit onder 45°C, vol op 75°C; handmatig direct", "风扇不可用: 未启用 overlay 或温控服务未运行": "Ventilator niet beschikbaar: overlay niet actief of service draait niet", "读取风扇状态失败": "Ventilatorstatus lezen mislukt", "风扇设置已保存, 立即生效": "Ventilatorinstellingen opgeslagen, direct toegepast"},
    "ru": {"风扇设置": "Вентилятор", "自动温控": "Авто (по температуре)", "手动定速": "Ручная скорость", "风扇转速": "Скорость вентилятора", "当前温度": "Текущая температура", "当前占空比": "Текущий ШИМ", "保存风扇设置": "Сохранить настройки вентилятора", "自动模式按温度调速: 45°C 以下停转, 75°C 全速; 手动模式立即生效": "Авто по температуре: выкл ниже 45°C, полностью при 75°C; ручной режим сразу", "风扇不可用: 未启用 overlay 或温控服务未运行": "Вентилятор недоступен: overlay не включён или служба не запущена", "读取风扇状态失败": "Не удалось прочитать состояние вентилятора", "风扇设置已保存, 立即生效": "Настройки вентилятора сохранены, применены сразу"},
    "ja": {"风扇设置": "ファン", "自动温控": "自動(温度)", "手动定速": "手動速度", "风扇转速": "ファン回転数", "当前温度": "現在温度", "当前占空比": "現在デューティ", "保存风扇设置": "ファン設定を保存", "自动模式按温度调速: 45°C 以下停转, 75°C 全速; 手动模式立即生效": "自動は温度連動: 45°C未満停止、75°Cで全速; 手動は即時反映", "风扇不可用: 未启用 overlay 或温控服务未运行": "ファン利用不可: overlay未有効またはサービス未実行", "读取风扇状态失败": "ファンの状態取得に失敗", "风扇设置已保存, 立即生效": "ファン設定を保存、即時反映"},
    "ko": {"风扇设置": "팬", "自动温控": "자동(온도)", "手动定速": "수동 속도", "风扇转速": "팬 속도", "当前温度": "현재 온도", "当前占空比": "현재 듀티", "保存风扇设置": "팬 설정 저장", "自动模式按温度调速: 45°C 以下停转, 75°C 全速; 手动模式立即生效": "자동은 온도 연동: 45°C 미만 정지, 75°C 최고속; 수동은 즉시 적용", "风扇不可用: 未启用 overlay 或温控服务未运行": "팬 사용 불가: overlay 미활성 또는 서비스 미실행", "读取风扇状态失败": "팬 상태 읽기 실패", "风扇设置已保存, 立即生效": "팬 설정 저장됨, 즉시 적용"},
}
for _fl, _fm in FAN_I18N.items():
    LANG_TABLE.setdefault(_fl, {}).update(_fm)
NET_I18N = {
    "en": {"网络设置": "Network", "有线网络": "Wired", "无线网络": "Wi-Fi", "自动获取 (DHCP)": "Automatic (DHCP)", "静态地址": "Static address", "IP 地址": "IP address", "掩码位数": "Prefix length", "网关": "Gateway", "DNS (逗号分隔)": "DNS (comma separated)", "应用有线设置": "Apply wired settings", "扫描无线": "Scan Wi-Fi", "无线密码 (留空为开放网络)": "Wi-Fi password (empty = open)", "连接无线": "Connect Wi-Fi", "忘记网络": "Forget network", "未检测到无线网卡": "No Wi-Fi adapter detected", "网络已应用: 90 秒内确认连接, 否则自动回滚": "Network applied: confirm within 90s or it rolls back", "确认连接": "Confirm connection", "已确认连接, 回滚取消": "Connection confirmed, rollback cancelled", "扫描中…": "Scanning…", "开放": "open", "参数无效": "Invalid parameters", "应用失败": "Apply failed", "有线设置已应用": "Wired settings applied", "无线连接已应用": "Wi-Fi connection applied", "无待确认变更": "No pending change"},
    "de": {"网络设置": "Netzwerk", "有线网络": "Kabel", "无线网络": "WLAN", "自动获取 (DHCP)": "Automatisch (DHCP)", "静态地址": "Statische Adresse", "IP 地址": "IP-Adresse", "掩码位数": "Präfixlänge", "网关": "Gateway", "DNS (逗号分隔)": "DNS (kommagetrennt)", "应用有线设置": "Kabeleinstellungen anwenden", "扫描无线": "WLAN scannen", "无线密码 (留空为开放网络)": "WLAN-Passwort (leer = offen)", "连接无线": "WLAN verbinden", "忘记网络": "Netzwerk vergessen", "未检测到无线网卡": "Kein WLAN-Adapter erkannt", "网络已应用: 90 秒内确认连接, 否则自动回滚": "Netzwerk angewendet: innerhalb 90s bestätigen, sonst Rollback", "确认连接": "Verbindung bestätigen", "已确认连接, 回滚取消": "Verbindung bestätigt, Rollback abgebrochen", "扫描中…": "Scanne…", "开放": "offen", "参数无效": "Ungültige Parameter", "应用失败": "Anwenden fehlgeschlagen", "有线设置已应用": "Kabeleinstellungen angewendet", "无线连接已应用": "WLAN-Verbindung angewendet", "无待确认变更": "Keine ausstehende Änderung"},
    "fr": {"网络设置": "Réseau", "有线网络": "Filaire", "无线网络": "Wi-Fi", "自动获取 (DHCP)": "Automatique (DHCP)", "静态地址": "Adresse statique", "IP 地址": "Adresse IP", "掩码位数": "Longueur de préfixe", "网关": "Passerelle", "DNS (逗号分隔)": "DNS (séparés par virgules)", "应用有线设置": "Appliquer le filaire", "扫描无线": "Scanner le Wi-Fi", "无线密码 (留空为开放网络)": "Mot de passe Wi-Fi (vide = ouvert)", "连接无线": "Connecter le Wi-Fi", "忘记网络": "Oublier le réseau", "未检测到无线网卡": "Aucune carte Wi-Fi détectée", "网络已应用: 90 秒内确认连接, 否则自动回滚": "Réseau appliqué : confirmez sous 90s sinon retour arrière", "确认连接": "Confirmer la connexion", "已确认连接, 回滚取消": "Connexion confirmée, retour arrière annulé", "扫描中…": "Scan…", "开放": "ouvert", "参数无效": "Paramètres invalides", "应用失败": "Échec de l'application", "有线设置已应用": "Réglages filaires appliqués", "无线连接已应用": "Connexion Wi-Fi appliquée", "无待确认变更": "Aucun changement en attente"},
    "it": {"网络设置": "Rete", "有线网络": "Cablata", "无线网络": "Wi-Fi", "自动获取 (DHCP)": "Automatico (DHCP)", "静态地址": "Indirizzo statico", "IP 地址": "Indirizzo IP", "掩码位数": "Lunghezza prefisso", "网关": "Gateway", "DNS (逗号分隔)": "DNS (separati da virgola)", "应用有线设置": "Applica cablata", "扫描无线": "Scansiona Wi-Fi", "无线密码 (留空为开放网络)": "Password Wi-Fi (vuota = aperta)", "连接无线": "Connetti Wi-Fi", "忘记网络": "Dimentica rete", "未检测到无线网卡": "Nessun adattatore Wi-Fi rilevato", "网络已应用: 90 秒内确认连接, 否则自动回滚": "Rete applicata: conferma entro 90s o rollback", "确认连接": "Conferma connessione", "已确认连接, 回滚取消": "Connessione confermata, rollback annullato", "扫描中…": "Scansione…", "开放": "aperta", "参数无效": "Parametri non validi", "应用失败": "Applicazione non riuscita", "有线设置已应用": "Impostazioni cablate applicate", "无线连接已应用": "Connessione Wi-Fi applicata", "无待确认变更": "Nessuna modifica in sospeso"},
    "es": {"网络设置": "Red", "有线网络": "Cableada", "无线网络": "Wi-Fi", "自动获取 (DHCP)": "Automático (DHCP)", "静态地址": "Dirección estática", "IP 地址": "Dirección IP", "掩码位数": "Longitud de prefijo", "网关": "Puerta de enlace", "DNS (逗号分隔)": "DNS (separados por coma)", "应用有线设置": "Aplicar cableada", "扫描无线": "Escanear Wi-Fi", "无线密码 (留空为开放网络)": "Contraseña Wi-Fi (vacía = abierta)", "连接无线": "Conectar Wi-Fi", "忘记网络": "Olvidar red", "未检测到无线网卡": "No se detectó adaptador Wi-Fi", "网络已应用: 90 秒内确认连接, 否则自动回滚": "Red aplicada: confirme en 90s o se revierte", "确认连接": "Confirmar conexión", "已确认连接, 回滚取消": "Conexión confirmada, reversión cancelada", "扫描中…": "Escaneando…", "开放": "abierta", "参数无效": "Parámetros inválidos", "应用失败": "Error al aplicar", "有线设置已应用": "Ajustes cableados aplicados", "无线连接已应用": "Conexión Wi-Fi aplicada", "无待确认变更": "Sin cambios pendientes"},
    "nl": {"网络设置": "Netwerk", "有线网络": "Bedraad", "无线网络": "Wi-Fi", "自动获取 (DHCP)": "Automatisch (DHCP)", "静态地址": "Statisch adres", "IP 地址": "IP-adres", "掩码位数": "Prefixlengte", "网关": "Gateway", "DNS (逗号分隔)": "DNS (komma-gescheiden)", "应用有线设置": "Bedraad toepassen", "扫描无线": "Wi-Fi scannen", "无线密码 (留空为开放网络)": "Wi-Fi-wachtwoord (leeg = open)", "连接无线": "Wi-Fi verbinden", "忘记网络": "Netwerk vergeten", "未检测到无线网卡": "Geen Wi-Fi-adapter gevonden", "网络已应用: 90 秒内确认连接, 否则自动回滚": "Netwerk toegepast: bevestig binnen 90s anders rollback", "确认连接": "Verbinding bevestigen", "已确认连接, 回滚取消": "Verbinding bevestigd, rollback geannuleerd", "扫描中…": "Scannen…", "开放": "open", "参数无效": "Ongeldige parameters", "应用失败": "Toepassen mislukt", "有线设置已应用": "Bedrade instellingen toegepast", "无线连接已应用": "Wi-Fi-verbinding toegepast", "无待确认变更": "Geen openstaande wijziging"},
    "ru": {"网络设置": "Сеть", "有线网络": "Проводная", "无线网络": "Wi-Fi", "自动获取 (DHCP)": "Автоматически (DHCP)", "静态地址": "Статический адрес", "IP 地址": "IP-адрес", "掩码位数": "Длина префикса", "网关": "Шлюз", "DNS (逗号分隔)": "DNS (через запятую)", "应用有线设置": "Применить проводную", "扫描无线": "Сканировать Wi-Fi", "无线密码 (留空为开放网络)": "Пароль Wi-Fi (пусто = открытая)", "连接无线": "Подключить Wi-Fi", "忘记网络": "Забыть сеть", "未检测到无线网卡": "Wi-Fi адаптер не обнаружен", "网络已应用: 90 秒内确认连接, 否则自动回滚": "Сеть применена: подтвердите за 90с, иначе откат", "确认连接": "Подтвердить подключение", "已确认连接, 回滚取消": "Подключение подтверждено, откат отменён", "扫描中…": "Сканирование…", "开放": "открытая", "参数无效": "Неверные параметры", "应用失败": "Не удалось применить", "有线设置已应用": "Проводные настройки применены", "无线连接已应用": "Wi-Fi подключение применено", "无待确认变更": "Нет ожидающих изменений"},
    "ja": {"网络设置": "ネットワーク", "有线网络": "有線", "无线网络": "Wi-Fi", "自动获取 (DHCP)": "自動 (DHCP)", "静态地址": "固定アドレス", "IP 地址": "IPアドレス", "掩码位数": "プレフィクス長", "网关": "ゲートウェイ", "DNS (逗号分隔)": "DNS (カンマ区切り)", "应用有线设置": "有線設定を適用", "扫描无线": "Wi-Fiスキャン", "无线密码 (留空为开放网络)": "Wi-Fiパスワード (空=オープン)", "连接无线": "Wi-Fi接続", "忘记网络": "ネットワークを削除", "未检测到无线网卡": "Wi-Fiアダプタ未検出", "网络已应用: 90 秒内确认连接, 否则自动回滚": "ネットワーク適用: 90秒以内に確認しないと自動ロールバック", "确认连接": "接続を確認", "已确认连接, 回滚取消": "接続確認済み、ロールバック取消", "扫描中…": "スキャン中…", "开放": "オープン", "参数无效": "パラメータ無効", "应用失败": "適用失敗", "有线设置已应用": "有線設定を適用しました", "无线连接已应用": "Wi-Fi接続を適用しました", "无待确认变更": "確認待ちの変更なし"},
    "ko": {"网络设置": "네트워크", "有线网络": "유선", "无线网络": "Wi-Fi", "自动获取 (DHCP)": "자동 (DHCP)", "静态地址": "고정 주소", "IP 地址": "IP 주소", "掩码位数": "프리픽스 길이", "网关": "게이트웨이", "DNS (逗号分隔)": "DNS (쉼표 구분)", "应用有线设置": "유선 설정 적용", "扫描无线": "Wi-Fi 스캔", "无线密码 (留空为开放网络)": "Wi-Fi 비밀번호 (비움=개방)", "连接无线": "Wi-Fi 연결", "忘记网络": "네트워크 잊기", "未检测到无线网卡": "Wi-Fi 어댑터 미검출", "网络已应用: 90 秒内确认连接, 否则自动回滚": "네트워크 적용: 90초 내 확인하지 않으면 자동 롤백", "确认连接": "연결 확인", "已确认连接, 回滚取消": "연결 확인됨, 롤백 취소", "扫描中…": "스캔 중…", "开放": "개방", "参数无效": "잘못된 매개변수", "应用失败": "적용 실패", "有线设置已应用": "유선 설정 적용됨", "无线连接已应用": "Wi-Fi 연결 적용됨", "无待确认变更": "대기 중인 변경 없음"},
}
for _nl, _nm in NET_I18N.items():
    LANG_TABLE.setdefault(_nl, {}).update(_nm)
NET2_I18N = {
    "en": {"个人热点": "Personal hotspot", "关闭": "Off", "开启": "On", "热点名称": "Hotspot name", "热点密码 (8-63位)": "Hotspot password (8-63 chars)", "连着 WiFi 时热点跟随同信道; 未连接默认 2.4G ch6。客户端分 192.168.50.x 并共享有线上网。": "While connected to Wi-Fi the hotspot follows the same channel; otherwise 2.4G ch6. Clients get 192.168.50.x and share wired internet.", "应用热点设置": "Apply hotspot", "热点设置已应用": "Hotspot settings applied", "蓝牙": "Bluetooth", "不可被发现": "Not discoverable", "可被发现": "Discoverable", "蓝牙名称": "Bluetooth name", "应用蓝牙设置": "Apply Bluetooth", "扫描蓝牙": "Scan Bluetooth", "蓝牙设置已应用": "Bluetooth settings applied", "配对完成": "Paired", "未检测到蓝牙": "No Bluetooth adapter detected", "已配对": "paired", "客户端": "clients"},
    "de": {"个人热点": "Persönlicher Hotspot", "关闭": "Aus", "开启": "Ein", "热点名称": "Hotspot-Name", "热点密码 (8-63位)": "Hotspot-Passwort (8-63 Zeichen)", "连着 WiFi 时热点跟随同信道; 未连接默认 2.4G ch6。客户端分 192.168.50.x 并共享有线上网。": "Mit WLAN verbunden folgt der Hotspot demselben Kanal; sonst 2.4G ch6. Clients erhalten 192.168.50.x und teilen das Kabel-Internet.", "应用热点设置": "Hotspot anwenden", "热点设置已应用": "Hotspot-Einstellungen angewendet", "蓝牙": "Bluetooth", "不可被发现": "Nicht sichtbar", "可被发现": "Sichtbar", "蓝牙名称": "Bluetooth-Name", "应用蓝牙设置": "Bluetooth anwenden", "扫描蓝牙": "Bluetooth scannen", "蓝牙设置已应用": "Bluetooth-Einstellungen angewendet", "配对完成": "Gekoppelt", "未检测到蓝牙": "Kein Bluetooth-Adapter erkannt", "已配对": "gekoppelt", "客户端": "Clients"},
    "fr": {"个人热点": "Point d'accès personnel", "关闭": "Désactivé", "开启": "Activé", "热点名称": "Nom du point d'accès", "热点密码 (8-63位)": "Mot de passe (8-63 caractères)", "连着 WiFi 时热点跟随同信道; 未连接默认 2.4G ch6。客户端分 192.168.50.x 并共享有线上网。": "Connecté au Wi-Fi, le point d'accès suit le même canal ; sinon 2.4G ch6. Les clients reçoivent 192.168.50.x et partagent l'internet filaire.", "应用热点设置": "Appliquer le point d'accès", "热点设置已应用": "Réglages du point d'accès appliqués", "蓝牙": "Bluetooth", "不可被发现": "Non visible", "可被发现": "Visible", "蓝牙名称": "Nom Bluetooth", "应用蓝牙设置": "Appliquer Bluetooth", "扫描蓝牙": "Scanner Bluetooth", "蓝牙设置已应用": "Réglages Bluetooth appliqués", "配对完成": "Appairé", "未检测到蓝牙": "Aucun adaptateur Bluetooth détecté", "已配对": "appairé", "客户端": "clients"},
    "it": {"个人热点": "Hotspot personale", "关闭": "Spento", "开启": "Acceso", "热点名称": "Nome hotspot", "热点密码 (8-63位)": "Password hotspot (8-63 caratteri)", "连着 WiFi 时热点跟随同信道; 未连接默认 2.4G ch6。客户端分 192.168.50.x 并共享有线上网。": "Connesso al Wi-Fi l'hotspot segue lo stesso canale; altrimenti 2.4G ch6. I client ricevono 192.168.50.x e condividono la rete cablata.", "应用热点设置": "Applica hotspot", "热点设置已应用": "Impostazioni hotspot applicate", "蓝牙": "Bluetooth", "不可被发现": "Non visibile", "可被发现": "Visibile", "蓝牙名称": "Nome Bluetooth", "应用蓝牙设置": "Applica Bluetooth", "扫描蓝牙": "Scansiona Bluetooth", "蓝牙设置已应用": "Impostazioni Bluetooth applicate", "配对完成": "Associato", "未检测到蓝牙": "Nessun adattatore Bluetooth rilevato", "已配对": "associato", "客户端": "client"},
    "es": {"个人热点": "Punto de acceso personal", "关闭": "Apagado", "开启": "Encendido", "热点名称": "Nombre del punto de acceso", "热点密码 (8-63位)": "Contraseña (8-63 caracteres)", "连着 WiFi 时热点跟随同信道; 未连接默认 2.4G ch6。客户端分 192.168.50.x 并共享有线上网。": "Conectado al Wi-Fi el punto de acceso sigue el mismo canal; si no, 2.4G ch6. Los clientes reciben 192.168.50.x y comparten la red cableada.", "应用热点设置": "Aplicar punto de acceso", "热点设置已应用": "Ajustes del punto de acceso aplicados", "蓝牙": "Bluetooth", "不可被发现": "No visible", "可被发现": "Visible", "蓝牙名称": "Nombre Bluetooth", "应用蓝牙设置": "Aplicar Bluetooth", "扫描蓝牙": "Escanear Bluetooth", "蓝牙设置已应用": "Ajustes Bluetooth aplicados", "配对完成": "Emparejado", "未检测到蓝牙": "No se detectó adaptador Bluetooth", "已配对": "emparejado", "客户端": "clientes"},
    "nl": {"个人热点": "Persoonlijke hotspot", "关闭": "Uit", "开启": "Aan", "热点名称": "Hotspotnaam", "热点密码 (8-63位)": "Hotspotwachtwoord (8-63 tekens)", "连着 WiFi 时热点跟随同信道; 未连接默认 2.4G ch6。客户端分 192.168.50.x 并共享有线上网。": "Verbonden met Wi-Fi volgt de hotspot hetzelfde kanaal; anders 2.4G ch6. Clients krijgen 192.168.50.x en delen bedraad internet.", "应用热点设置": "Hotspot toepassen", "热点设置已应用": "Hotspotinstellingen toegepast", "蓝牙": "Bluetooth", "不可被发现": "Niet zichtbaar", "可被发现": "Zichtbaar", "蓝牙名称": "Bluetooth-naam", "应用蓝牙设置": "Bluetooth toepassen", "扫描蓝牙": "Bluetooth scannen", "蓝牙设置已应用": "Bluetooth-instellingen toegepast", "配对完成": "Gekoppeld", "未检测到蓝牙": "Geen Bluetooth-adapter gevonden", "已配对": "gekoppeld", "客户端": "clients"},
    "ru": {"个人热点": "Личная точка доступа", "关闭": "Выкл", "开启": "Вкл", "热点名称": "Имя точки доступа", "热点密码 (8-63位)": "Пароль (8-63 символа)", "连着 WiFi 时热点跟随同信道; 未连接默认 2.4G ch6。客户端分 192.168.50.x 并共享有线上网。": "При подключении к Wi-Fi точка следует тому же каналу; иначе 2.4G ch6. Клиенты получают 192.168.50.x и общий проводной интернет.", "应用热点设置": "Применить точку доступа", "热点设置已应用": "Настройки точки применены", "蓝牙": "Bluetooth", "不可被发现": "Не видимый", "可被发现": "Видимый", "蓝牙名称": "Имя Bluetooth", "应用蓝牙设置": "Применить Bluetooth", "扫描蓝牙": "Сканировать Bluetooth", "蓝牙设置已应用": "Настройки Bluetooth применены", "配对完成": "Сопряжено", "未检测到蓝牙": "Bluetooth адаптер не обнаружен", "已配对": "сопряжено", "客户端": "клиентов"},
    "ja": {"个人热点": "パーソナルホットスポット", "关闭": "オフ", "开启": "オン", "热点名称": "ホットスポット名", "热点密码 (8-63位)": "パスワード (8-63文字)", "连着 WiFi 时热点跟随同信道; 未连接默认 2.4G ch6。客户端分 192.168.50.x 并共享有线上网。": "Wi-Fi接続中はホットスポットは同一チャネルに従う; 未接続時は2.4G ch6。クライアントは192.168.50.xを取得し有線インターネットを共有。", "应用热点设置": "ホットスポット適用", "热点设置已应用": "ホットスポット設定を適用", "蓝牙": "Bluetooth", "不可被发现": "検出不可", "可被发现": "検出可能", "蓝牙名称": "Bluetooth名", "应用蓝牙设置": "Bluetooth適用", "扫描蓝牙": "Bluetoothスキャン", "蓝牙设置已应用": "Bluetooth設定を適用", "配对完成": "ペアリング完了", "未检测到蓝牙": "Bluetoothアダプタ未検出", "已配对": "ペア済", "客户端": "クライアント"},
    "ko": {"个人热点": "개인 핫스팟", "关闭": "끄기", "开启": "켜기", "热点名称": "핫스팟 이름", "热点密码 (8-63位)": "핫스팟 비밀번호 (8-63자)", "连着 WiFi 时热点跟随同信道; 未连接默认 2.4G ch6。客户端分 192.168.50.x 并共享有线上网。": "Wi-Fi 연결 중 핫스팟은 동일 채널을 따름; 미연결 시 2.4G ch6. 클라이언트는 192.168.50.x를 받고 유선 인터넷을 공유.", "应用热点设置": "핫스팟 적용", "热点设置已应用": "핫스팟 설정 적용됨", "蓝牙": "Bluetooth", "不可被发现": "검색 불가", "可被发现": "검색 가능", "蓝牙名称": "Bluetooth 이름", "应用蓝牙设置": "Bluetooth 적용", "扫描蓝牙": "Bluetooth 스캔", "蓝牙设置已应用": "Bluetooth 설정 적용됨", "配对完成": "페어링 완료", "未检测到蓝牙": "Bluetooth 어댑터 미검출", "已配对": "페어링됨", "客户端": "클라이언트"},
}
for _n2l, _n2m in NET2_I18N.items():
    LANG_TABLE.setdefault(_n2l, {}).update(_n2m)
NET3_I18N = {
    "en": {"频段": "Band", "信道": "Channel", "自动": "Auto", "手动": "Manual", "频段/信道: 自动跟随已连 WiFi; 手动仅在未连 WiFi 时生效 (2.4G:1-13, 5G:149-165)。": "Band/channel: auto follows the connected Wi-Fi; manual only applies when Wi-Fi is disconnected (2.4G:1-13, 5G:149-165).", "热点须与已连WiFi同频段; 自选请先断开WiFi": "Hotspot must share the connected Wi-Fi band; disconnect Wi-Fi to choose manually", "热点须与已连WiFi同信道; 自选请先断开WiFi": "Hotspot must share the connected Wi-Fi channel; disconnect Wi-Fi to choose manually", "信道无效(2.4G:1-13, 5G:149-165)": "Invalid channel (2.4G:1-13, 5G:149-165)", "频段与信道不匹配": "Band and channel do not match"},
    "de": {"频段": "Band", "信道": "Kanal", "自动": "Auto", "手动": "Manuell", "频段/信道: 自动跟随已连 WiFi; 手动仅在未连 WiFi 时生效 (2.4G:1-13, 5G:149-165)。": "Band/Kanal: Auto folgt dem verbundenen WLAN; manuell nur ohne WLAN-Verbindung (2.4G:1-13, 5G:149-165).", "热点须与已连WiFi同频段; 自选请先断开WiFi": "Hotspot muss das WLAN-Band teilen; für manuelle Wahl WLAN trennen", "热点须与已连WiFi同信道; 自选请先断开WiFi": "Hotspot muss den WLAN-Kanal teilen; für manuelle Wahl WLAN trennen", "信道无效(2.4G:1-13, 5G:149-165)": "Ungültiger Kanal (2.4G:1-13, 5G:149-165)", "频段与信道不匹配": "Band und Kanal passen nicht zusammen"},
    "fr": {"频段": "Bande", "信道": "Canal", "自动": "Auto", "手动": "Manuel", "频段/信道: 自动跟随已连 WiFi; 手动仅在未连 WiFi 时生效 (2.4G:1-13, 5G:149-165)。": "Bande/canal : auto suit le Wi-Fi connecté ; manuel seulement sans Wi-Fi (2.4G:1-13, 5G:149-165).", "热点须与已连WiFi同频段; 自选请先断开WiFi": "Le point d'accès doit partager la bande Wi-Fi ; déconnectez le Wi-Fi pour choisir", "热点须与已连WiFi同信道; 自选请先断开WiFi": "Le point d'accès doit partager le canal Wi-Fi ; déconnectez le Wi-Fi pour choisir", "信道无效(2.4G:1-13, 5G:149-165)": "Canal invalide (2.4G:1-13, 5G:149-165)", "频段与信道不匹配": "Bande et canal incompatibles"},
    "it": {"频段": "Banda", "信道": "Canale", "自动": "Auto", "手动": "Manuale", "频段/信道: 自动跟随已连 WiFi; 手动仅在未连 WiFi 时生效 (2.4G:1-13, 5G:149-165)。": "Banda/canale: auto segue il Wi-Fi connesso; manuale solo senza Wi-Fi (2.4G:1-13, 5G:149-165).", "热点须与已连WiFi同频段; 自选请先断开WiFi": "L'hotspot deve condividere la banda Wi-Fi; disconnetti il Wi-Fi per scegliere", "热点须与已连WiFi同信道; 自选请先断开WiFi": "L'hotspot deve condividere il canale Wi-Fi; disconnetti il Wi-Fi per scegliere", "信道无效(2.4G:1-13, 5G:149-165)": "Canale non valido (2.4G:1-13, 5G:149-165)", "频段与信道不匹配": "Banda e canale non corrispondono"},
    "es": {"频段": "Banda", "信道": "Canal", "自动": "Auto", "手动": "Manual", "频段/信道: 自动跟随已连 WiFi; 手动仅在未连 WiFi 时生效 (2.4G:1-13, 5G:149-165)。": "Banda/canal: auto sigue el Wi-Fi conectado; manual solo sin Wi-Fi (2.4G:1-13, 5G:149-165).", "热点须与已连WiFi同频段; 自选请先断开WiFi": "El punto de acceso debe compartir la banda Wi-Fi; desconecta el Wi-Fi para elegir", "热点须与已连WiFi同信道; 自选请先断开WiFi": "El punto de acceso debe compartir el canal Wi-Fi; desconecta el Wi-Fi para elegir", "信道无效(2.4G:1-13, 5G:149-165)": "Canal inválido (2.4G:1-13, 5G:149-165)", "频段与信道不匹配": "Banda y canal no coinciden"},
    "nl": {"频段": "Band", "信道": "Kanaal", "自动": "Auto", "手动": "Handmatig", "频段/信道: 自动跟随已连 WiFi; 手动仅在未连 WiFi 时生效 (2.4G:1-13, 5G:149-165)。": "Band/kanaal: auto volgt de verbonden Wi-Fi; handmatig alleen zonder Wi-Fi (2.4G:1-13, 5G:149-165).", "热点须与已连WiFi同频段; 自选请先断开WiFi": "Hotspot moet de Wi-Fi-band delen; verbreek Wi-Fi om handmatig te kiezen", "热点须与已连WiFi同信道; 自选请先断开WiFi": "Hotspot moet het Wi-Fi-kanaal delen; verbreek Wi-Fi om handmatig te kiezen", "信道无效(2.4G:1-13, 5G:149-165)": "Ongeldig kanaal (2.4G:1-13, 5G:149-165)", "频段与信道不匹配": "Band en kanaal komen niet overeen"},
    "ru": {"频段": "Диапазон", "信道": "Канал", "自动": "Авто", "手动": "Вручную", "频段/信道: 自动跟随已连 WiFi; 手动仅在未连 WiFi 时生效 (2.4G:1-13, 5G:149-165)。": "Диапазон/канал: авто следует подключённому Wi-Fi; вручную только без Wi-Fi (2.4G:1-13, 5G:149-165).", "热点须与已连WiFi同频段; 自选请先断开WiFi": "Точка доступа должна использовать диапазон Wi-Fi; отключите Wi-Fi для выбора", "热点须与已连WiFi同信道; 自选请先断开WiFi": "Точка доступа должна использовать канал Wi-Fi; отключите Wi-Fi для выбора", "信道无效(2.4G:1-13, 5G:149-165)": "Неверный канал (2.4G:1-13, 5G:149-165)", "频段与信道不匹配": "Диапазон и канал не совпадают"},
    "ja": {"频段": "バンド", "信道": "チャネル", "自动": "自動", "手动": "手動", "频段/信道: 自动跟随已连 WiFi; 手动仅在未连 WiFi 时生效 (2.4G:1-13, 5G:149-165)。": "バンド/チャネル: 自動は接続中Wi-Fiに追従; 手動はWi-Fi未接続時のみ有効 (2.4G:1-13, 5G:149-165)。", "热点须与已连WiFi同频段; 自选请先断开WiFi": "ホットスポットはWi-Fiと同バンド必須; 手動選択はWi-Fi切断後に", "热点须与已连WiFi同信道; 自选请先断开WiFi": "ホットスポットはWi-Fiと同チャネル必須; 手動選択はWi-Fi切断後に", "信道无效(2.4G:1-13, 5G:149-165)": "無効なチャネル (2.4G:1-13, 5G:149-165)", "频段与信道不匹配": "バンドとチャネルが不一致"},
    "ko": {"频段": "대역", "信道": "채널", "自动": "자동", "手动": "수동", "频段/信道: 自动跟随已连 WiFi; 手动仅在未连 WiFi 时生效 (2.4G:1-13, 5G:149-165)。": "대역/채널: 자동은 연결된 Wi-Fi를 따름; 수동은 Wi-Fi 미연결 시에만 유효 (2.4G:1-13, 5G:149-165).", "热点须与已连WiFi同频段; 自选请先断开WiFi": "핫스팟은 Wi-Fi와 동일 대역 필수; 수동 선택은 Wi-Fi 해제 후", "热点须与已连WiFi同信道; 自选请先断开WiFi": "핫스팟은 Wi-Fi와 동일 채널 필수; 수동 선택은 Wi-Fi 해제 후", "信道无效(2.4G:1-13, 5G:149-165)": "잘못된 채널 (2.4G:1-13, 5G:149-165)", "频段与信道不匹配": "대역과 채널 불일치"},
}
for _n3l, _n3m in NET3_I18N.items():
    LANG_TABLE.setdefault(_n3l, {}).update(_n3m)
_DFS_MSG = "已连WiFi处于雷达信道, 不支持并发热点; 请先断开WiFi或改连2.4G/5G 149-165"
NET4_I18N = {
    "en": {_DFS_MSG: "Connected Wi-Fi is on a radar (DFS) channel; concurrent hotspot unsupported. Disconnect Wi-Fi or switch to 2.4G / 5G 149-165 first"},
    "de": {_DFS_MSG: "Verbundenes WLAN nutzt einen Radar-(DFS-)Kanal; gleichzeitiger Hotspot nicht möglich. WLAN trennen oder auf 2.4G / 5G 149-165 wechseln"},
    "fr": {_DFS_MSG: "Le Wi-Fi connecté est sur un canal radar (DFS) ; point d'accès simultané impossible. Déconnectez le Wi-Fi ou passez en 2.4G / 5G 149-165"},
    "it": {_DFS_MSG: "Il Wi-Fi connesso è su un canale radar (DFS); hotspot simultaneo non supportato. Disconnetti il Wi-Fi o passa a 2.4G / 5G 149-165"},
    "es": {_DFS_MSG: "El Wi-Fi conectado está en un canal radar (DFS); punto de acceso simultáneo no soportado. Desconecta el Wi-Fi o cambia a 2.4G / 5G 149-165"},
    "nl": {_DFS_MSG: "Verbonden Wi-Fi gebruikt een radar-(DFS-)kanaal; gelijktijdige hotspot niet mogelijk. Verbreek Wi-Fi of schakel naar 2.4G / 5G 149-165"},
    "ru": {_DFS_MSG: "Подключённый Wi-Fi на радарном (DFS) канале; одновременная точка доступа невозможна. Отключите Wi-Fi или перейдите на 2.4G / 5G 149-165"},
    "ja": {_DFS_MSG: "接続中Wi-Fiはレーダー(DFS)チャネルのため同時ホットスポット不可; Wi-Fi切断または2.4G/5G 149-165へ変更してください"},
    "ko": {_DFS_MSG: "연결된 Wi-Fi가 레이더(DFS) 채널이라 동시 핫스팟 불가; Wi-Fi 해제 또는 2.4G/5G 149-165로 변경하세요"},
}
for _n4l, _n4m in NET4_I18N.items():
    LANG_TABLE.setdefault(_n4l, {}).update(_n4m)
I18N_JS = json.dumps(LANG_TABLE, ensure_ascii=False, separators=(",", ":"))
LANG_JS = json.dumps([[c, n] for c, n in LANG_NAMES], ensure_ascii=False, separators=(",", ":"))
MAX_UPLOAD = 100 * 1024 * 1024  # 通用文件上传上限 100MB (皮肤/音频有自己的更小限制)
MAX_JSON = 1024 * 1024          # 普通 JSON 接口请求体上限 1MB (文件管理/改密码/推送配置等)
SOCK_TIMEOUT = 30               # 单连接读写超时秒数, 防慢连接长期占线程

# ---------------- 版本与在线升级 (OTA) ----------------
# 升级方式: 从 GitHub 仓库拉 version.json (清单) 比对版本号, 再下 sentry-viewer.py 覆盖本机文件并重启。
# 国内直连 raw.githubusercontent 与 fastly/testingcf.jsdelivr 会被 RST 或 TLS 干扰 (实测 1 秒内断开),
# 下面这几个是逐个实测能通的 (数字为实测耗时); 全部并发竞速, 任一可用即可, 抖动时互相补位。
APP_VERSION = "2.8.44"
OTA_REPO = os.environ.get("TSF_OTA_REPO", "chyou38/rock3a-tslyun")
_OTA_DEFAULT = ",".join([
    "https://ghfast.top/https://raw.githubusercontent.com/%s/main" % OTA_REPO,       # 1.1s
    "https://gcore.jsdelivr.net/gh/%s@main" % OTA_REPO,                              # 1.1s
    "https://ghproxy.net/https://raw.githubusercontent.com/%s/main" % OTA_REPO,      # 2.4s
    "https://gh-proxy.org/https://raw.githubusercontent.com/%s/main" % OTA_REPO,     # 3.2s
    "https://gh-proxy.com/https://raw.githubusercontent.com/%s/main" % OTA_REPO,     # 时通时断, 兜底
    "https://raw.githubusercontent.com/%s/main" % OTA_REPO,                          # 海外线路
    "https://cdn.jsdelivr.net/gh/%s@main" % OTA_REPO,                                # 海外线路
])
OTA_SOURCES = [s.strip().rstrip("/") for s in os.environ.get("TSF_OTA_SOURCES", _OTA_DEFAULT).split(",") if s.strip()]
OTA_BACKUP = os.environ.get("TSF_OTA_BACKUP", "/opt/tesla-sentry/sentry-viewer.bak.py")
OTA_STATE = os.environ.get("TSF_OTA_STATE", "/opt/tesla-sentry/ota-state.json")
OTA_SRC_PREF = os.path.join(os.path.dirname(OTA_STATE) or ".", "ota-src.json")  # 记住上次最快的源
_OTA_CACHE = {"t": 0.0, "data": None}


def _http_get(url, timeout=10, limit=8 << 20):
    req = urllib.request.Request(url, headers={"User-Agent": "tsf-ota/" + APP_VERSION, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit)


def _src_order():
    """上次成功的源排最前 (竞速同时成功时优先选它)"""
    order = list(OTA_SOURCES)
    try:
        with open(OTA_SRC_PREF, encoding="utf-8") as f:
            good = json.load(f).get("last_good")
        if good in order:
            order.remove(good)
            order.insert(0, good)
    except Exception:
        pass
    return order


def _err_kind(ex):
    """把网络异常翻成一句人话, 更新页里直接能看出是哪个源被墙/超时/被劫持"""
    s = str(ex)
    if isinstance(ex, urllib.error.HTTPError):
        return "HTTP %d" % ex.code
    if isinstance(ex, socket.timeout) or "timed out" in s:
        return "超时"
    if "RemoteDisconnected" in s or "Connection reset" in s or "reset by peer" in s or "EOF occurred" in s:
        return "连接被阻断"
    if "CERTIFICATE_VERIFY_FAILED" in s or "certificate verify failed" in s:
        return "证书被劫持"
    if "Name does not resolve" in s or "Name or service not known" in s or "getaddrinfo" in s:
        return "DNS 解析失败"
    if "BAD_RECORD_MAC" in s or "WRONG_VERSION_NUMBER" in s or "SSL" in s or "TLS" in s:
        return "TLS 被干扰"
    if "IncompleteRead" in s or "incomplete" in s.lower():
        return "下载中断"
    return type(ex).__name__


def _race_get(path, timeout, limit, validate=None, collect=False, grace=1.0):
    """并发竞速所有下载源, 单个源被墙/超时不影响其它源。
    collect=False: 谁先返回【通过校验】的数据就用谁, 返回 (data, base)。
    collect=True:  返回 [(base, data), ...] 全部成功的源 —— 首次成功后最多再等 grace 秒
                   就收工, 由调用方按版本号挑最新的 (镜像 CDN 常缓存旧清单)。
    全挂时抛错, 并把每个源的失败原因列出来。"""
    lock = threading.Lock()
    got, bad, done = [], {}, [0]
    first_ok = [0.0]

    def worker(base):
        try:
            data = _http_get(base + path, timeout=timeout, limit=limit)
            if data and (validate is None or validate(data)):
                with lock:
                    got.append((base, data))
                    if not first_ok[0]:
                        first_ok[0] = time.time()
            else:
                with lock:
                    bad[base] = "内容校验失败"
        except Exception as ex:
            with lock:
                bad[base] = _err_kind(ex)
        finally:
            with lock:
                done[0] += 1

    order = _src_order()
    for base in order:
        threading.Thread(target=worker, args=(base,), daemon=True).start()
    deadline = time.time() + timeout + 1.5
    while time.time() < deadline:
        with lock:
            n_ok, n_done, t0 = len(got), done[0], first_ok[0]
        if n_done >= len(order):
            break
        if not collect and n_ok:
            break
        if collect and n_ok and t0 and time.time() > t0 + grace:
            break
        time.sleep(0.05)
    with lock:
        results, fails = list(got), dict(bad)
    if not results:
        detail = " · ".join("%s %s" % (urllib.parse.urlsplit(b).netloc, fails.get(b, "无响应"))
                            for b in order)
        raise RuntimeError("所有下载源均不可用 (%s)" % detail)
    results.sort(key=lambda x: order.index(x[0]))
    base = results[0][0]
    try:   # 记住本次最快的源
        with open(OTA_SRC_PREF, "w", encoding="utf-8") as f:
            json.dump({"last_good": base, "at": int(time.time())}, f)
    except OSError:
        pass
    return results if collect else (results[0][1], base)


def _vtuple(v):
    out = []
    for x in re.split(r"[.\-+]", str(v)):
        out.append(int(x) if x.isdigit() else 0)
    return tuple(out) or (0,)


def _api_manifest(timeout=5):
    """GitHub API 实时读 version.json (返回 base64 内容), 不受 raw/镜像 CDN 缓存影响。
    国内不可达时静默失败, 由调用方退回原有的多源竞速结果。"""
    try:
        url = "https://api.github.com/repos/%s/contents/version.json?ref=main" % OTA_REPO
        req = urllib.request.Request(url, headers={
            "User-Agent": "tsf-ota/" + APP_VERSION,
            "Accept": "application/vnd.github+json",
            "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            outer = json.loads(r.read(256 << 10).decode("utf-8", "replace"))
        return json.loads(base64.b64decode(outer["content"]).decode("utf-8", "replace"))
    except Exception:
        return None


def ota_latest(force=False):
    """读仓库 version.json (含版本号/日期/更新说明), 并发竞速多个源, 结果缓存 10 分钟"""
    now = time.time()
    if not force and _OTA_CACHE["data"] and now - _OTA_CACHE["t"] < 600:
        return _OTA_CACHE["data"]

    def ok(raw):
        try:
            j = json.loads(raw.decode("utf-8", "replace"))
            return bool(str(j.get("version") or "").strip())
        except Exception:
            return False

    # raw / ghfast / jsDelivr 的 CDN 会缓存旧清单数分钟, 导致「更新」页显示过期的
    # 版本号与更新说明。并行再问一次 GitHub API (实时, 无 CDN 缓存), 拿到就优先用。
    fresh = []

    def api_worker():
        j = _api_manifest()
        if j and str(j.get("version") or "").strip():
            fresh.append(j)

    apith = threading.Thread(target=api_worker, daemon=True)
    apith.start()

    raced = None
    base = None
    err = ""
    try:
        res = _race_get("/version.json?ts=%d" % int(now), timeout=6, limit=256 << 10,
                        validate=ok, collect=True, grace=1.5)
    except RuntimeError as ex:
        res, err = [], str(ex)
    parsed = []
    for b, r in res:
        try:
            jj = json.loads(r.decode("utf-8", "replace"))
        except Exception:
            continue
        if str(jj.get("version") or "").strip():
            parsed.append((b, jj))
    if parsed:
        # 镜像 CDN 会缓存旧清单 (实测 ghfast.top 拿到过 2.8.10 而仓库已是 2.8.13),
        # 所以不取"第一个成功的", 而是取版本号最大的那个; 同版本时 _race_get 已按源优先级排好
        best = 0
        for i in range(1, len(parsed)):
            if _vtuple(parsed[i][1].get("version")) > _vtuple(parsed[best][1].get("version")):
                best = i
        base, raced = parsed[best]
    else:
        # 一个源都没给出可用清单: 走 GitHub API 兜底, 再不行就把各源的失败原因报上去
        j2 = _api_manifest(timeout=6)
        if j2 and str(j2.get("version") or "").strip():
            raced, base = j2, "https://api.github.com"
        else:
            raise RuntimeError(err or "下载源返回的清单无法解析")
    # jsDelivr 等镜像的 @main 缓存可能停留在很旧的版本: 比本机还旧就多等一会儿实时源
    stale = _vtuple(raced.get("version")) < _vtuple(APP_VERSION)
    if not fresh and apith.is_alive():
        apith.join(timeout=2.5 if stale else 1.2)
    if not fresh and stale:
        j2 = _api_manifest(timeout=3)
        if j2 and str(j2.get("version") or "").strip():
            fresh.append(j2)
    if fresh:
        j, base = fresh[0], "https://api.github.com"
    else:
        j = raced
    j["_base"] = base
    _OTA_CACHE.update({"t": now, "data": j})
    return j


def ota_check(force=False):
    cur = APP_VERSION
    out = {"ok": True, "current": cur, "latest": "", "date": "", "notes": [],
           "has_update": False, "source": "", "error": "",
           "rollback_ready": os.path.isfile(OTA_BACKUP),
           "auto": load_settings().get("auto_update", True),
           "auto_checked": AUTO_UPD["last_check"], "auto_msg": AUTO_UPD["last_result"]}
    try:
        j = ota_latest(force)
    except Exception as ex:
        out["error"] = str(ex)
        return out
    latest = str(j.get("version"))
    out.update({"latest": latest, "date": j.get("date") or "", "notes": j.get("notes") or [],
                "has_update": _vtuple(latest) > _vtuple(cur),
                "source": urllib.parse.urlsplit(j["_base"]).netloc})
    return out


def _self_paths():
    """需要一起覆盖的程序文件 (只认正式安装位置; 临时副本只改它自己)"""
    here = os.path.realpath(__file__)
    known = ("/opt/tesla-sentry/sentry-viewer.py", "/root/sentry-viewer.py")
    paths = [here]
    if here not in known:
        return paths
    for p in known:
        try:
            rp = os.path.realpath(p)
        except OSError:
            continue
        if os.path.isfile(rp) and rp not in paths:
            paths.append(rp)
    return paths


def _write_each(paths, data):
    for p in paths:
        d = os.path.dirname(p) or "."
        tmp = os.path.join(d, ".ota-tmp.py")
        with open(tmp, "wb") as f:
            f.write(data)
        try:
            os.chmod(tmp, 0o644)
        except OSError:
            pass
        os.replace(tmp, p)          # 原子替换, 不会出现半个文件


# OTA 配套脚本: (仓库相对路径, 设备文件名, 特征串, 最小字节数)
# 旧版 OTA 只替换 sentry-viewer.py, 导致改了归档/同步脚本后老设备点"更新"永远不生效。
OTA_SIDECARS = (
    ("scripts/tesla-gadget.sh", "tesla-gadget.sh", b"#!/bin/sh", 200),
    ("scripts/tesla-sync.sh", "tesla-sync.sh", b"#!/bin/sh", 200),
    ("scripts/usb-selfheal.sh", "usb-selfheal.sh", b"#!/bin/sh", 200),
    ("scripts/tesla-img.sh", "tesla-img.sh", b"#!/bin/sh", 200),
    ("scripts/tsf-check.sh", "tsf-check.sh", b"#!/bin/sh", 200),
    ("tesla-live-sync.py", "tesla-live-sync.py", b"def do_sync", 2000),
)


def _ota_sidecars(base):
    """主程序升级后顺带更新配套脚本; 返回 (已更新列表, 跳过/失败数)。
    只覆盖设备上已存在的同名文件; 单个失败不阻断主升级。"""
    d = os.environ.get("TSF_DIR", "/opt/tesla-sentry")
    if not os.path.isdir(d):
        return [], len(OTA_SIDECARS)
    updated, failed = [], 0
    for rel, name, sig, minsz in OTA_SIDECARS:
        dest = os.path.join(d, name)
        if not os.path.isfile(dest):
            failed += 1
            continue
        try:
            data = _http_get("%s/%s?ts=%d" % (base, rel, int(time.time())),
                             timeout=8, limit=512 << 10)
            if len(data) < minsz or sig not in data:
                raise ValueError("内容校验未通过")
            with open(dest, "rb") as f:
                if f.read() == data:
                    continue                      # 内容一致, 不重写也不重启
            tmp = dest + ".ota-tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            try:
                os.chmod(tmp, 0o755 if name.endswith(".sh") else 0o644)
            except OSError:
                pass
            os.replace(tmp, dest)
            updated.append(name)
        except Exception as ex:
            failed += 1
            try:
                os.unlink(dest + ".ota-tmp")
            except OSError:
                pass
            print("ota sidecar skip %s: %s" % (name, ex))
    # 在线同步脚本换了必须重启常驻进程, 否则跑的还是旧代码
    if "tesla-live-sync.py" in updated:
        try:
            if os.path.isfile("/etc/init.d/tesla-live"):
                subprocess.Popen(["/etc/init.d/tesla-live", "restart"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif shutil.which("systemctl"):
                subprocess.Popen(["systemctl", "restart", "tesla-live.service"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    return updated, failed


def _ota_restart():
    """优先交给 procd 的 init 脚本重启 (找不到就原地 exec)"""
    here = os.path.realpath(__file__)
    d = os.path.dirname(here)
    cands = []
    for name in ("tesla-viewer", "sentry-viewer"):
        p = "/etc/init.d/" + name
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                txt = f.read()
        except OSError:
            txt = ""
        score = 2 if here in txt else (1 if ("sentry-viewer.py" in txt or (d and d in txt)) else 0)
        cands.append((score, p))
    cands.sort(reverse=True)
    if cands and cands[0][0] > 0:
        try:
            subprocess.Popen([cands[0][1], "restart"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return
        except Exception:
            pass
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception:
        os._exit(1)


def ota_apply():
    """下载并安装最新版; 返回 (成功?, 提示/错误)"""
    try:
        j = ota_latest(True)
    except Exception as ex:
        return False, "检查更新失败: %s" % ex
    latest = str(j.get("version"))
    if not _vtuple(latest) > _vtuple(APP_VERSION):
        return False, "当前已是最新版本 (%s)" % APP_VERSION
    # 下载也走多源竞速: 清单来源的镜像突然挂了, 其它源照样能补位
    try:
        data, base = _race_get("/sentry-viewer.py?ts=%d" % int(time.time()), timeout=60, limit=8 << 20,
                               validate=lambda d: len(d) > 50000 and b"APP_VERSION" in d)
    except Exception as ex:
        return False, "下载失败: %s" % ex
    # 1) 完整性校验: 大小 + 特征串 + 内嵌版本号必须与清单一致
    if len(data) < 50000:
        return False, "下载不完整 (%d 字节)" % len(data)
    if b"APP_VERSION" not in data or b"--ota-check" not in data or b"/api/events" not in data:
        return False, "文件校验失败: 不是有效的查看器程序"
    m = re.search(rb'APP_VERSION\s*=\s*"([^"]+)"', data)
    if not m or m.group(1).decode() != latest:
        return False, "版本校验失败 (文件 %s / 清单 %s)" % (m.group(1).decode() if m else "?", latest)
    # 2) 语法 + 启动自检: 新程序自己声明的 --ota-check 只做模块加载, 不启服务
    tmp = "/tmp/tsf-ota-new.py"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        r = subprocess.run([sys.executable or "python3", "-m", "py_compile", tmp],
                           capture_output=True, timeout=90)
        if r.returncode != 0:
            return False, "语法校验失败: " + r.stderr.decode("utf-8", "replace")[-160:]
        r = subprocess.run([sys.executable or "python3", tmp, "--ota-check"],
                           capture_output=True, timeout=90)
        if r.returncode != 0 or b"ok" not in (r.stdout or b"").lower():
            return False, "启动自检失败: " + (r.stderr or r.stdout).decode("utf-8", "replace")[-160:]
        os.remove(tmp)
    except Exception as ex:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False, "校验异常: %s" % ex
    # 3) 备份旧版 (回滚用) 后逐份原子替换
    here = os.path.realpath(__file__)
    try:
        os.makedirs(os.path.dirname(OTA_BACKUP) or ".", exist_ok=True)
        shutil.copy2(here, OTA_BACKUP)
    except Exception as ex:
        return False, "备份旧版本失败: %s" % ex
    prev = APP_VERSION
    try:
        _write_each(_self_paths(), data)
    except Exception as ex:
        return False, "写入失败: %s" % ex
    # 3.5) 配套脚本一并升级 (单个失败不影响主程序; 内容一致则跳过不重写)
    try:
        upd, skipped = _ota_sidecars(base)
    except Exception as ex:
        upd, skipped = [], len(OTA_SIDECARS)
        print("ota sidecars error:", ex)
    try:
        with open(OTA_STATE, "w", encoding="utf-8") as f:
            json.dump({"applied": latest, "prev": prev, "at": int(time.time())}, f)
    except OSError:
        pass
    msg = "已升级到 %s, 服务正在重启…" % latest
    if upd:
        msg += " 配套脚本已更新: " + ", ".join(upd)
    if skipped:
        msg += " (%d 个脚本源不可用, 保持原文件)" % skipped
    threading.Timer(1.2, _ota_restart).start()
    return True, msg


def ota_rollback():
    if not os.path.isfile(OTA_BACKUP):
        return False, "没有可用的备份 (还没升级过)"
    try:
        with open(OTA_BACKUP, "rb") as f:
            data = f.read()
    except OSError as ex:
        return False, "读取备份失败: %s" % ex
    if len(data) < 50000:
        return False, "备份文件不完整, 已放弃回滚"
    try:
        _write_each(_self_paths(), data)
    except Exception as ex:
        return False, "写入失败: %s" % ex
    threading.Timer(1.0, _ota_restart).start()
    return True, "已回滚到上一版本, 服务正在重启…"


# ---------- 自动更新 ----------
# 设置存在 settings.json (与 auth.conf 同目录), 默认开启: 每 5 分钟看一次有没有新版本,
# 有就等"没人在看视频/没有导出任务"的窗口自动升级 (升级只重启本服务, 约 5 秒)
SETTINGS_FILE = os.environ.get("TSF_SETTINGS", "/opt/tesla-sentry/settings.json")
AUTO_UPD = {"last_check": 0, "last_result": "", "last_apply": 0, "next_try": 0}

# ---- 标题栏标识 (logo + 名称): 默认内置这张图, 设置里可换成自己的 ----
BRAND_DIR = os.path.join(os.path.dirname(SETTINGS_FILE) or "/opt/tesla-sentry", "brand")
BRAND_NAME_MAX = 24
BRAND_NAME_DEFAULT = "TSL哨兵云盘"
# 168x168 JPEG, 已缩到够 34px 显示 3 倍屏用; 内嵌避免设备上没有图片文件
BRAND_LOGO_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAQDAwQDAwQEBAQFBQQFBwsHBwYGBw4KCggLEA4RERAOEA8SFBoWEhMYEw8QFh8XGBsb"
    "HR0dERYgIh8cIhocHRz/2wBDAQUFBQcGBw0HBw0cEhASHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc"
    "HBwcHBwcHBz/wgARCACoAKgDASIAAhEBAxEB/8QAGwAAAAcBAAAAAAAAAAAAAAAAAAECAwQFBgf/xAAaAQACAwEBAAAAAAAAAAAA"
    "AAABBAACAwUG/9oADAMBAAIQAxAAAAHmUW5jdDlVsByKs4okqz1I0iAEAQCMgSIyhdlQpcgZlxZJekx0/ZfZiCHuVa5HRYld5hKk"
    "qPmDOQkqWCybogaNZSEDOFIdbkkNNOwNrJMN2KgbLXtHKZprHMzrcjJUiNdku1Lt8WlRdPfPMotK62ZGo7VQo0yJZlxZH2wuBkGJ"
    "JjL7RCApAJKTOFoXeuC9yWe4pbLiaYyaS3BpXKXItSA3OhkKacbtVpbZwAEJJramzFIcQCerzWqxZznVMzolXo1LssIL5xeg0Oym"
    "RPT00NXQbTP3zq25cXZVlSRaiQ4JHGw2DZsh+FUqQWLNhqM10pPoXHN+kYmWYf2NbfPm8vaSr0p3LOqzZymL6BjtU6Vt5hvmuBII"
    "JLjYK9Dm+i5MUO2uiV6KNMl2piZ7S5SaayXlNJbNwrOstnR0tnQhivyujz2qdJGmRGecQWCHGpccRrfYHRZ7d6fq5ynTdr5vPYdd"
    "i2HACuYcwa7ilmUlqVlROZmtbR6Gk3Qza7mv2SiisFqW8HU5e+TDjZZ690uOZb/n9q2KNLkeTlaXSaJzEWItsalZ0tUtyK4yJUuE"
    "zz3YFrXXzyYkDVPtHPOkZ/ocblqdJWI9WT1nkO2U6G5bQtPo4TRqodb3MN2zBNDTOZhUlhmNlxPhSGErnPWmftmyHw3zunU4DvKT"
    "XAC9dTgKu9DuAOD6qZMAtJjYGlazMAUvkYIDfMb0AElNLAbShADXH//EACsQAAICAQMEAgEEAgMAAAAAAAECAAMEBRESEBMhMSAi"
    "QQYUIzAVMiQlM//aAAgBAQABBQIlYQTO14Y/1gxV36ejTdwKfYJdyBpjbLLbOZ/rEr8FxD0xsg0uT5tAQZlhP9O02gHTaBoGh64d"
    "/E5VvEWuXbrt42ipyJGx+RE9dfU3mbbycj4fiaPh8x7ldRdCNvi3+xEB2+DHkz++v4mm0hNFmjrzOcoTK67eW9+wyxG2hhiQ/D8T"
    "CG2m2LxfTLO3fqq7ZsA8cYegjfDaGHwei1/8aYtn/X5FHJlVqWyD3jVSrwLAI6bJ66GHqfQje4BMLH72Bl437ezG++hGhWwcwrW5"
    "s4yhbXc4F8ppG2SmyHoYer+Ivt/cXwcDUExsaxKcmvRt0pGOacfNLtZRgBJVmYmni/XsVo+ZRaxTvJbg2VxqiqwiCGOdyD5sHkxK"
    "2ZKMZrLF061ZphYXZCjtmkvqWaHoGXpy/wCKTSc6/IbT0e+nBrpW1FIyqFl1fBj1PQNuqrzmLkLiBXc5Gn5OXkPVQrV3f+R+uWyi"
    "wvTfP2dzynDWqX+mPi+ZQ8n4gzHxnsUYhvsfBpy0xcfGrlniu0/xkcmoPFAAYYfV0J3l5l8b5aF/LSMIFK9OlNK1C2W1ntvyrZc7"
    "aUEGAAi1wJkNLLNpaZcI/qEQw9P00/2rUbbQCWvxazUT2rdXpxmObjZiaTlmxA/1yHlzz2bFly+D7rCCW2VAEfT8TRLu1n12bgP4"
    "5bzWaMjKuo0XUkqq/TPcNuJUlWnY4xwW2Sxpb5O20t9N5naBmTVxUyxdutbmt8PIFqc4jS+qu8UhVFj/AMZTkV8Qv9XMO/JjL2i+"
    "YgmWI485eI4jDbrouRvSrbhDN9zk6n2rMrV+YTVUiawkruFwcRvEY7S+zeV/VFEyv9mXc2UK65mnFIR0wbv270nwky7xjY+PiHUI"
    "um4FMtvoqiiq5lCpHeWvLrIPu35rXiuS2824KzTNTnM3C4OMYmdvtzR8vnTW8sQWNkV2GNp/M06TXVO1xjKZxmQwWWPuUPbXHHJs"
    "q3YKDa7KbLS0dueRYOQ7X2zqCJQ70Lj5S31pZvOHMVULVBPBmRxWZGWqS/J5HeFyxrHYrtc2t9MdBed//8QAJBEAAgIBAwUBAAMA"
    "AAAAAAAAAAECEQMEEiEQICIxQVETMEL/2gAIAQMBAT8BUvwgv3urpmw7uUSx0zS4/wDT6pWV3ZNPvdkI7VXXSxuV/hihvnRJU6/o"
    "jGzRe2RTxz3GTym2ihru0zipeRixbJ2vTMq8Rab7NmzFfDM2J+0NV2IjGCSbMThVxI+jJFT9ixQRFcGpguzTxUpUyGOEfZx8IkkJ"
    "301A+uB1NDQjc68Uc/SEfozObaGY5qa46Y3vipD4P4/rG/xkRsycsmvEswZHB8CzRas0GdNuJIrpRmyUI1E6RuX0gJmmm0rMUt0E"
    "2SYiTqJkk2yH6ah3Kij/xAAjEQACAgEEAgIDAAAAAAAAAAAAAQIRAxASIUEgMAQTIjFR/9oACAECAQE/AWib/nox5K4YpGafXqhl"
    "2qiTt3rnlSom9sbE7V+huj5HQ2pRoi6jon5ZrrgnkuPJB8jzdRN0+0Y59MT8W5PgyKV8jIPaPI3pibvwytpWPJJ6VpWkF4ZFcRDE"
    "ueXo2IhrOLi9J/i6E7EbdEREUTipIeNp0fLx8KRFn2oeUsxqz9GKO5m19DKMkUyaqVEEMXLEqJGHhaf/xAA2EAABAwEGBAMGBAcA"
    "AAAAAAABAAIRAxASICExQSIwUWEEE3EjMkJSgaEUM5HBQGJjcnOS8P/aAAgBAQAGPwLLOyXFZc/PMIPYcHbmwd13Fo6IPZ7rv4CD"
    "gyXlu9x32RKk4gAMzzoGgx1PEEcLAYsc4bYjzWjd1MmyqN4VUDSeXOOgP6YTm9CuxTt5AP2wDHGF7/5gLPD/AOMI1PmcU7/oTX/E"
    "dbIX0U4zhqUwJLzkgNWuAIKovbq1kFUSB6+sq/5ctcLr29URq1cDCZV65B6LPVHGBgCLAPaSUGOO2RVSi7RpTY0XltzKvVi273V0"
    "uJZtkuEO/RXhkUWhZjkT1QV4DJqa0ES4bqS7Togx+9gAGyY1rZr1MmDp3QZ4aoHeLa4PLj7z1+I8SYcXXiXZkpxESTJgZIZZ2GMY"
    "CAT7wmdlSFV7PDgiQ54kAJ1248MEkHKUyuMu3SxtRTvpMLgqM/1XHV/RZWnkAsTT8LlS/EDNgi8zIleX4aiO5UWgFZWk4xb3bkgI"
    "XESoAQsyQa7JTyhbWZ6HBPRFmUL2u6JpFEH4THI9pouFC1nR/DgPh6Trt7MZ6qD4im/tP7o1fFuvH5WH915VClTpDruo++PS3TVG"
    "xrxq0ymuGjhNsVGh0KNgjbHJJ+UYPL3YfspshEU4ujfqgHEBo2XC+FxkeqBbph9bIsIIyKq1J00tv+k+i7WVKp2Cv1bzKH3cvymf"
    "XNQC0BTca7uRijYK8U4rOxjPmKJbpZUYfllNY48TbBegtGy4H3QodVqOPRT5M/3LJsYb29kLsFdFjejRb5g9F5zNWFNew25a9eRJ"
    "94qAolHy2/Ur/8QAJhABAAICAgICAgMAAwAAAAAAAQARITFBURBxYYGRoSCx0TDw8f/aAAgBAQABPyHvn3xEcC/1EiMfEJa0mPF+"
    "H+eE1wxgpfRgLWntJ249QXroi/C4j5Sv+AZiytEWb+aGETLvmQNl4gYbR4fBHzT5AhHwDTeeJ+s1AuLj/cQHN8RsnjmV4CMiiVUs"
    "DqV56iU+MrL0hkiTbEFh5lu3gKgeHTw/7+DUcr7zMvF6SXE6lSpVnjAiX/c12VYJqJLpmB/M4CH8BDYfuyM4JlPUg6YddHA+pUrE"
    "CNKTJs5a+GZPkmhsdkw9QTAVMs9/wNp3C/6BUV7kP3NxehqYegOTnCVNmafNQYUC2YemDMqsxcR1Mq7zPWoLDqPi+vqx1GFbf/hE"
    "B1/bjJkCrrlxMH1YU19QUXqn3Ft6NMyLF5ysm0u/xHMGGosVN9Ezm5iS9qNeI+iRCn7NDJ9RXz+gYlr3ePRy3B8DHY9nEs0XNl7g"
    "I+LE365Fi5mrdh4leDqcIO/BQ1GYvsjxIIqerSImvkdEsIIKNkG2djik3CK6sp8sFmIYxK3uOk54g72fHzE6w+Wk2l+zcKsqxvYd"
    "ksH5I+SbzMhKAwMGoGISvcCnFwiCwQnsaW1N0eK9kFUJyTGJebizXb6RewV+nA8VwRnlBov0Qy7YKB6OIhFeU1yaRV7lucQbhLxF"
    "4vTiYT8kwJSfaWoWF4DBMW8Ac1b7h3vK21yRDvmJOxTUe1AGgs5A91j1Lo1A8M9sGhMqO4JaTCEupx4qglWpZHgV2fBKYDMFDpiN"
    "Kc+fyy8yG8Phm1JMvvFWyEIVMM7wZrBROYxPyj4p8iv+yBgUGJY5R1cIiA6mQOVjvhDdyJjzpcIq7mQ1AGD/ALOBLsy64apzKmCD"
    "PrB4C+7p/qUkQa8As34ypEb6zKG/QLZcdTZVJGiuB3aDnMfMSVRMiG1H7VRUM2VJzbHbxTlwP+P6lTmUQcc0dZmlPcwi2mmvwlnf"
    "pH3He8xavuU0reVcs0EuXwCrMYUjy8cETUS49hFo8NIMH1FowBMirlbDYTS+JUdAURQxxzCRZafeRLl3g0DM7MuZeSqMo8+oiR3H"
    "w6J4XtK+L0mEOYi6zViOvjDRN116alkCvRiwW9eEh+ZkMsJDkYe67godZdJMDYhOAKxKZUvuIj2bg0ptZipisVgJfKjQY/zIKN9c"
    "5P3APi4qCh8QwQoD1CZmlIwJncxURB/phwhBGWLVXCNus+ou5Jm+IvmGAY069kFQi6MmIsuW4HogXscGJZPmrlT+sQvcvzg8RfSw"
    "W2ohnG2DSdShPYzhAeK5cphVpAFa3OmtvUFJpp2MxpH9RyZiqDbBMc9qYDcz5MRRES5dUwO2Ew+jxqbLrBuDjfyyyZWX/9oADAMB"
    "AAIAAwAAABAE8oKMexr5P+oTRye1jS2g4vxiJft0W5Y1eZM6l/pi0XFUQI+DvGRIXDOkjpmGWzb/ABviU69I3bKfxjbH1FG3N/z9"
    "T+fBrEwLCz8O7LDKmuMHf/8AoXn/AEL6IF33/8QAIBEBAQEBAAIDAAMBAAAAAAAAAQARITFBECBRcYGRsf/aAAgBAwEBPxA/EcN8"
    "vr5mBZvb/wBuRkr8iLC4ss+Mz4DG5AJ+TV+kAP3b/wCPsftkjwhx/iCY8Q/QMdZZPw/AcgmOuI2p4T/IuTzMeISAd2Uh6T+X0GyJ"
    "d9k3sIb1cVxuHYCMNJPoqEQbPQDC6OSmtswI3Jcy8vnff1/so7FV5qep5yF/ZMD/AGg1nhfiV1LW3Khx0jE9x1pbEXkGRwWROzIn"
    "YLrnuL7mC8ekFZCbmtu8geYjhLWHP4Hv/EgJDQ9Ek8yyQuuy7Fom9omiQer/xAAeEQEAAwADAQEBAQAAAAAAAAABABEhEDFBUSBh"
    "gf/aAAgBAgEBPxBfYN1+DwPF3wlxcoKR4c2X+bmojsuaH6j0PJWfUuX+H5L4GyGVu5VD5Fy5cfh74CPu5VHYZ7epZjcFKkVKbAeo"
    "crUVT/jC03HTkfYcMitw1GHNbRiyIvcfqG5AmsybXDhlwSlSmbUH1H8jW1MKi4jxWHgLzUgsoizyLvDJO0tK0kzyOA7O4AbA4zgS"
    "0VXHESyKR0iHY4j8YLCA7MQlDDGRbUAqQV9n/8QAJhABAAICAgICAgMBAQEAAAAAAQARITFBUWFxgZGhwRCx0fDh8f/aAAgBAQAB"
    "PxBih5SaPtjZ+IoeoKU4h3pcyweYsrLuUp/ms5iEGmZwYBvPESLgSNQYCC3a/UqiwvDk8MADJTMx6A4GIbYS9RoGMRGkNyr/AISI"
    "Rhr+HUC4ma3Foa9yq1FfXmMLFYPPpl1YyRI5gJSNcaQalMcajJAUJYoHeMXLUuJuaIuWZly7GU9XBtEvyyrjMsJRnuDNaI6KEqDI"
    "GnqWWemXZDTjPBljyWQFauobC0ov7CMZa5SxC8eJom4UmDMucdzsbjKRA7MRMLSNQsRKgcwKV5iW8XK3nDHaCkYMK1Gd5Prhdygn"
    "SOp1QL7l7bpiLCoETPqD7oERGjWMISvxr5iyf/pDBQIDOTcdTlUILEcDlmw7gLxV4hCzWF+ZcX0xKq3+GPB5tSyDfK7iDoEHMqoG"
    "WP4QZgw7L5U/ZA+sgDA6CF2PxDfk0aLDDIhctSmu5dcFJcndzGCpw9PczH5OyI/BJzCJqLC/4GCV88Sqojj+BfuIFHhHVnGX5P8A"
    "sNSl89ImXCqBUu8HmlryToKAQckHqoKOmGGQOyXM4xMX3AFsvAkrVN1KKksFTOFAGuT0RD6Cj1OwMJrAWolhfXFN/wBk5eSFxw+v"
    "Ahq1x2N6+44RtJ5Ftf3UvXCXSjjwKdeY/mkN0iwP3UuzDWPCbhohpQfJBva0vDBEfDUCG/aXGdjUVlaY7yh3Ua7yv+0BhU94tszV"
    "KOmalmgaOCNvi6PmMJVYrR8is+pW57NaUfi4eShYMiy/TA+bSVznAQtSm+jgOr91s0y1uqps/McOzi5e+oqqqoKlDqoFpFL6mYuW"
    "5ULio2mWszxmDmPtjL3LVc3KKVkq44D8wXq08y2JqooXCfv1DIjFZTk/7MA8ssc71DzmUlEvzgynXqYRKjgcqkywTTVM/GX/ANl3"
    "UUlw7ChTpPTLbWmFfhbi5Xd0eVnMolexM15i5XacBErErYQWV3iMRI1olYBxFtczrwSOOqs9MQbw/wBxMH8NxX9wmulGLrI+YNc6"
    "ifT/ACXDrWePh9fuaOHFVqXlvuahYjyYQz9AcsoYMIhuTqmxox3CDkDoo5xZou/qFBHEetoOB4IN1DI2srNUqsn4h0DQgDETd2x4"
    "nW1FUNPNS5lwWFtM/qIEF4F73DPL5mEd/iM1O8lbcVylDXNsMThzw4Dj0XERZtESo0ibpsxh2QGivxLDFYerxMSBVQNoWOL+6g1A"
    "PcD2NTvrv+8iTLyyLCNaniVi3ctdDuAJHTHM2Z9Uc+0cR2EwRIh5pa/CRojGjbBiCw0DdjyFX47lKcRs3TVm3xAZo0BgoPQQBdCp"
    "pCdTIksEJfiRLiBdRSt26jMOLwMrN8kqE7j8zMzM1DyEp15M2fcIKIUkf8dsoCFas637h33fRBU4MzCIN4QTTny8xTaG5hGFMuOs"
    "wNWZvQV7fMKiqLAirrUAnDLGKuIifxCQaOZZZZYOI3Jj9pSrEq4aoNN9r9TI6hmMwl7fxALVQHnmcuQDs9zZ/mOqvdGoYsORI9MT"
    "O3s8lWP1BlYVaQ1kdyl5ExT3ZG7ZU/JGYmFY9Yhii8xCSxhrUENwFOskOSLMHC72l/l+UevbFSpcXzDVbS7TSEatU4vcU6AXh4X4"
    "RvG0iDsPwfcDWRiLdqbfuIr70qnNcS2WaxK0ty7BCdGYhDkuCjQ4iAwgLGdyxFmgb5y2VLsi0RPKU/KufWMzS6/UsIQdTeOWP9i+"
    "deEySp1cbwBxLGxaRqvcJJuCgMI9x0pKGohu2PaxcwoOYr74iW7zAeiA9HgmC5Ig5DENs9whEGxghuIpzvuH02fJC3z4npUVv2kt"
    "pUxNjb4Ixm9oGe65gGkOf8FRvB0IH/IcsORkZUpVJzFecpbR7ZSjuCG5YjKNwyGhbKCXG1NBrmKazI5LiJOSXJcopEO0T9H4i6wA"
    "G9jACsXqAjuItZcQxVL+ebft2+owKaze+W06TdUA9EBAXii/rMxR5wo+iH4fzONx1HCOYEcqqC+pfbKhxrbiO2ZcBMRAvMSxRSrq"
    "XINh6Zf6gaK1lGpbIac1Ah4gPTcQi0FuRaH41Ey0+4CJcmOKjuv3L8Ny2T1Daf4d/BDCQ5zP5jQVTiiWQlIuWvZLIHJ5jgGy4fQA"
    "sSzab5jOOncvIrWcX1Bhd8EFXEqzgHlxHdzN5lM4DUPCcMPYqZJ1foWnxiCFRFOVyPqBHpCJrgI8Q9wfFwXGPIxaFO1zMiHiEMCY"
    "iEtF4YAuz0yzhNBDFAC06lEVVFcQpajIy8kMiFtD+if/2Q=="
)


def load_settings():
    d = {"auto_update": True, "ui_style": "default", "brand_name": "", "brand_logo": ""}
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            j = json.load(f)
        if isinstance(j, dict):
            if "auto_update" in j:
                d["auto_update"] = bool(j["auto_update"])
            st = str(j.get("ui_style") or "")
            if st in ("default", "apple", "claude", "pixel"):
                d["ui_style"] = st
            # 自定义标题名: 只留纯文本 (页面与登录页都会用到, 不让 HTML 混进来)
            nm = str(j.get("brand_name") or "").strip()[:BRAND_NAME_MAX]
            nm = nm.replace("<", "").replace(">", "").replace("&", "").replace('"', "").replace("'", "")
            if nm:
                d["brand_name"] = nm
            # 自定义图标: 只认 BRAND_DIR 里的裸文件名, 带路径的一律丢弃
            lg = str(j.get("brand_logo") or "")
            if lg and "/" not in lg and "\\" not in lg and lg.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                d["brand_logo"] = lg
    except (OSError, ValueError):
        pass
    return d


def save_settings(patch):
    d = load_settings()
    d.update(patch or {})
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE) or ".", exist_ok=True)
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, SETTINGS_FILE)
    except OSError:
        pass
    return d


def brand_logo_bytes():
    """当前标题图标: 有自定义就用自定义, 没有就用内置默认图。
    永远返回一张图, 前端不用为 404 做兜底 (img 破图比没有更难看)。"""
    lg = load_settings().get("brand_logo") or ""
    if lg:
        fp = os.path.join(BRAND_DIR, lg)
        if os.path.isfile(fp):
            try:
                with open(fp, "rb") as f:
                    return f.read(), ("image/png" if lg.lower().endswith(".png") else
                                      "image/webp" if lg.lower().endswith(".webp") else "image/jpeg")
            except OSError:
                pass
    try:
        return base64.b64decode(BRAND_LOGO_B64), "image/jpeg"
    except (ValueError, TypeError):
        return b"", "image/jpeg"


def brand_name():
    """自定义标题名; 空串表示用默认名 (前端按语言取默认值)"""
    return load_settings().get("brand_name") or ""


def brand_logo_ver():
    """自定义图标的 mtime, 前端拿它当 ?v= 破缓存 (同名覆盖也能立刻刷新)"""
    lg = load_settings().get("brand_logo") or ""
    if lg:
        try:
            return int(os.path.getmtime(os.path.join(BRAND_DIR, lg)))
        except OSError:
            return 0
    return 0


def brand_clear_files():
    try:
        for f in os.listdir(BRAND_DIR):
            try:
                os.remove(os.path.join(BRAND_DIR, f))
            except OSError:
                pass
    except OSError:
        pass


def _update_window_ok():
    """自动升级前探一下: 有人在拉视频/正在导出时先不动, 免得把人正在看的东西打断"""
    try:
        if MEDIA_ACTIVE[0] > 0:
            return False
    except Exception:
        pass
    with STITCH_LOCK:
        if any(j.get("state") == "running" for j in STITCH_JOBS.values()):
            return False
    return True


def auto_update_loop():
    time.sleep(90)                       # 开机先让同步与服务稳定
    while True:
        try:
            if not load_settings().get("auto_update", True):
                time.sleep(300)
                continue
            if time.time() < AUTO_UPD["next_try"]:
                time.sleep(60)
                continue
            j = ota_check(False)
            AUTO_UPD["last_check"] = int(time.time())
            if j.get("error"):
                AUTO_UPD["last_result"] = "检查失败: " + j["error"]
                AUTO_UPD["next_try"] = time.time() + 1800
                time.sleep(60)
                continue
            if not j.get("has_update"):
                AUTO_UPD["last_result"] = "已是最新 (%s)" % APP_VERSION
                AUTO_UPD["next_try"] = time.time() + 1800
                time.sleep(60)
                continue
            AUTO_UPD["last_result"] = "发现 v%s, 等待空闲后自动升级" % j.get("latest")
            for _ in range(30):          # 最多等 30 分钟的空闲窗口
                if _update_window_ok():
                    break
                time.sleep(60)
            if not _update_window_ok():
                AUTO_UPD["next_try"] = time.time() + 1800
                time.sleep(60)
                continue
            ok, msg = ota_apply()
            AUTO_UPD["last_apply"] = int(time.time())
            AUTO_UPD["last_result"] = ("自动升级: " if ok else "自动升级失败: ") + str(msg)
            if ok:
                time.sleep(30)           # ota_apply 已安排 1.2s 后重启, 进程会被替换
            AUTO_UPD["next_try"] = time.time() + 1800
            time.sleep(60)
        except Exception as ex:
            AUTO_UPD["last_result"] = "自动更新异常: %s" % ex
            AUTO_UPD["next_try"] = time.time() + 1800
            time.sleep(120)











HTML = r"""<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TSL哨兵云盘</title>
<style id="base">
:root {
  color-scheme: dark;
  --bg:#0e1216; --headbg:#171d24; --panel:#1c232c; --panel2:#232b35; --chipbg:#1e252e;
  --line:#232b34; --line2:#2a333d; --text:#e8eaed; --muted:#98a4b0; --muted2:#8b96a3;
  --accent:#e8443f; --blue:#2f6ee0; --shadow:0 4px 14px #00000055; --headline:#ffffff0d;
  /* 播放器子页面专用 */
  --stage:#0d1117;                        /* 视频区域始终深色, 两种主题都不变 */
  --amberbg:rgba(245,158,11,.14); --amber:#eab063; --amberb:#f7c67e; --amberline:rgba(245,158,11,.22);
}
html[data-theme="light"] {
  color-scheme: light;
  --bg:#f2f4f7; --headbg:#ffffff; --panel:#ffffff; --panel2:#eef1f5; --chipbg:#ffffff;
  --line:#e4e8ee; --line2:#d9dfe6; --text:#17191c; --muted:#5c6773; --muted2:#78838f;
  --accent:#e8443f; --blue:#2f6ee0; --shadow:0 2px 10px #0f172a14; --headline:#0f172a0d;
  --amberbg:rgba(245,158,11,.16); --amber:#9a5b00; --amberb:#875000; --amberline:rgba(245,158,11,.34);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background:var(--bg); color:var(--text); font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
  transition:background .25s,color .25s; }
/* 内联 SVG 图标: 尺寸跟字号走 (1em), 颜色吃 currentColor, 所以深浅色/四套风格都不用单独改 */
.ic { width:1.15em; height:1.15em; flex:0 0 auto; fill:none; stroke:currentColor; stroke-width:1.85;
  stroke-linecap:round; stroke-linejoin:round; vertical-align:-.15em; }
header h1 .ic { width:22px; height:22px; margin-right:6px; color:var(--accent); }
/* 标题栏图标: 圆形头像, 尺寸固定不随字号走 (换图后不用改样式) */
header h1 .blogo { width:34px; height:34px; border-radius:50%; flex:0 0 auto; object-fit:cover;
  background:var(--panel2); box-shadow:0 0 0 1px var(--line); }
#theme .ic, #gear .ic { width:19px; height:19px; }
.panel h2 .ic { width:16px; height:16px; margin-right:7px; color:var(--accent); }
.stab .ic { width:14px; height:14px; margin-right:5px; }
.fm-bar button .ic, .mini .ic { width:13px; height:13px; margin-right:4px; }
button.stab { display:inline-flex; align-items:center; justify-content:center; }
.pdl .ic { width:19px; height:19px; }
header { padding:12px 16px; background:var(--headbg); display:flex; flex-wrap:wrap; align-items:center; gap:10px; position:sticky; top:0; z-index:10; box-shadow:0 1px 0 var(--headline); }
header h1 { font-size:16px; font-weight:700; white-space:nowrap; letter-spacing:.5px; flex:0 0 auto;
  display:flex; align-items:center; gap:8px; }
header .sub { font-size:12px; color:var(--muted); white-space:nowrap; }
#live { margin-left:auto; min-width:0; flex:0 1 auto; }
#livedot { flex:0 0 7px; }
#livetxt { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tabs { display:flex; gap:6px; overflow-x:auto; scrollbar-width:none; }
.tabs::-webkit-scrollbar { display:none; }
.tab { padding:7px 14px; border-radius:18px; background:var(--panel2); color:var(--muted); cursor:pointer; font-size:12.5px; font-weight:600; border:1px solid transparent; white-space:nowrap; flex:0 0 auto; transition:background .15s,color .15s; }
.tab .tn { margin-left:5px; opacity:.62; font-variant-numeric:tabular-nums; }
.tab .tn::before { content:'('; } .tab .tn::after { content:')'; }
.tab:hover { color:var(--text); }
.tab.active { background:var(--text); color:var(--bg); box-shadow:none; }
html[data-theme="light"] .tab.active { background:#17191c; color:#fff; }
.filters { display:none; gap:6px; overflow-x:auto; padding:10px 16px 0; scrollbar-width:none; align-items:center; }
.filters.show { display:flex; }
.filters + .filters { padding-top:8px; }
.filters::-webkit-scrollbar { display:none; }
/* 窄屏: 两行筛选本来就是横向滚动 (不是换行), 右侧常被切一半看着像坏了;
   加一层渐隐遮罩提示"还能往右滑", 并留出尾部留白让最后一颗胶囊能完整滚出来 */
@media (max-width:640px){
  .filters.show { padding-right:28px;
    -webkit-mask-image:linear-gradient(to right,#000 calc(100% - 28px),transparent);
    mask-image:linear-gradient(to right,#000 calc(100% - 28px),transparent); }
}
.flab { font-size:11.5px; color:var(--muted2); flex:0 0 auto; letter-spacing:.5px; }
.chip.d.on { background:var(--blue); border-color:var(--blue); }
.chip.pick { border-style:dashed; background:var(--chipbg); color:var(--muted);
  position:sticky; right:0; z-index:2; box-shadow:-10px 0 12px var(--bg); }
.chip.pick:hover { color:var(--text); }
/* 原生日期选择器本体: 藏起来只用来唤起系统日历 */
.dpick { position:absolute; left:0; top:0; width:1px; height:1px; opacity:0; border:0; padding:0;
  pointer-events:none; }
.chip { padding:8px 13px; border-radius:14px; background:var(--chipbg); color:var(--muted); border:1px solid var(--line2);
  font-size:12px; cursor:pointer; white-space:nowrap; flex:0 0 auto; transition:background .15s,color .15s; }
.chip:hover { color:var(--text); border-color:var(--muted2); }
.chip.on { background:var(--blue); border-color:var(--blue); color:#fff; }
.chip .n { opacity:.62; margin-left:4px; font-variant-numeric:tabular-nums; }
/* 存储卡: 默认只露「虚拟U盘」一行, 右下角小箭头展开归档区/总占用
   (行距刻意压紧, 收起时约 40px, 手机首屏别占太多) */
.storwrap { padding:8px 16px 0; }
.storcard { position:relative; background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:8px 13px 9px; box-shadow:var(--shadow); }
.storrow { display:flex; justify-content:space-between; align-items:baseline; gap:10px; margin-bottom:4px; }
.storrow + .storbar { margin-bottom:7px; }
.storbar:last-child { margin-bottom:0; }
.storlab { font-size:12px; color:var(--text); font-weight:600; }
.storval { font-size:11.5px; color:var(--muted); font-variant-numeric:tabular-nums; white-space:nowrap; }
/* 进度条右侧留出小箭头的位子, 三行等宽 */
.storbar { height:4px; margin-right:24px; border-radius:2px; background:var(--line2); overflow:hidden; }
.storbar i { display:block; height:100%; width:0; background:var(--blue); border-radius:2px; transition:width .4s; }
.storextra { display:none; }
.storcard.open .storextra { display:block; }
/* 系统状态: 与三条占用行分层 —— 细分隔线 + 三等分指标格 (标签在上/数值在下),
   不再把三个值挤成一串灰字; 右侧同样留 24px 给折叠箭头, 与进度条右边缘对齐 */
.storsys { margin-top:9px; padding-top:8px; border-top:1px solid var(--line2); }
.storsys .storlab { display:block; margin-bottom:6px; }
.sysgrid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px; margin-right:24px; }
.syscell { min-width:0; background:var(--panel2); border:1px solid var(--line);
  border-radius:8px; padding:5px 7px 6px; }
.syscell .k { display:block; font-size:10px; line-height:1.3; color:var(--muted2); }
.syscell .v { display:block; margin-top:2px; font-size:12.5px; line-height:1.35; font-weight:600;
  color:var(--text); font-variant-numeric:tabular-nums; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.syscell .v .u { font-size:10px; font-weight:400; color:var(--muted2); margin-left:1px; }
.stortog { position:absolute; right:4px; bottom:3px; width:22px; height:20px; padding:0; border:0; border-radius:6px;
  background:transparent; color:var(--muted2); cursor:pointer; display:flex; align-items:center; justify-content:center;
  -webkit-tap-highlight-color:transparent; }
.stortog svg { width:13px; height:13px; transition:transform .2s; }
.stortog:hover { color:var(--text); background:var(--panel2); }
.storcard.open .stortog svg { transform:rotate(180deg); }
/* 主题切换按钮: 自动/浅色/深色 循环 */
#theme { background:var(--panel2); border:none; color:var(--muted); font-size:15px; cursor:pointer; border-radius:10px; width:36px; height:32px; }
#theme:hover { color:var(--text); }
@media (max-width:640px){
  /* 顶栏压成两行: 第一行 标题+同步状态+主题/设置, 第二行 4 个等宽页签 */
  header { padding:9px 12px 8px; gap:8px; }
  header h1 { font-size:15px; }
  header h1 .blogo { width:28px; height:28px; }
  header .sub { display:none; }
  #live { order:3; margin-left:0; max-width:108px; padding:4px 8px; }
  #theme { order:4; margin-left:auto; } #gear { order:5; margin-left:0; } #out { order:6; margin-left:0; }
  /* 页签: 单行「分段控件」—— 灰槽里浮起一块选中的, 比两行卡片矮一半;
     计数收成右侧小徽章, 「实时预览」没有计数也不会跟旁边几个对不齐 */
  .tabs { order:10; width:100%; margin-left:0; gap:2px; overflow:visible;
    background:var(--panel2); border:1px solid var(--line); border-radius:13px; padding:3px; }
  .tab { flex:1 1 0; min-width:0; display:flex; flex-direction:row; align-items:center;
    justify-content:center; gap:4px; padding:7px 2px; font-size:12px; line-height:1.2;
    border-radius:10px; background:transparent; border:none; overflow:hidden; }
  .tab .tl { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .tab .tn { flex:0 0 auto; display:inline-block; margin-left:0; padding:0 5px;
    font-size:10.5px; line-height:1.4; font-weight:700; border-radius:7px;
    background:#ffffff14; color:var(--muted); opacity:1; }
  html[data-theme="light"] .tab .tn { background:#0f172a10; }
  .tab .tn::before, .tab .tn::after { content:none; }
  .tab.active { box-shadow:0 1px 4px #0000004d; }
  html[data-theme="light"] .tab.active { box-shadow:0 1px 4px #0f172a29; }
  .tab.active .tn { background:#ffffff26; color:inherit; }
  .filters { padding-left:12px; padding-right:12px; }
  .chip { padding:8px 12px; }
  /* 播放器手机端紧凑化: 面板/卡片占高更小, 视频尽量多露 */
  .pscroll { padding:2px 8px 10px; gap:8px; }
  .tpanel { padding:10px 12px 8px; }
  .tp-spd { font-size:26px; }
  .tp-date { font-size:12px; } .tp-loc { font-size:11.5px; }
  .tp-tag { height:20px; font-size:11px; padding:0 8px; }
  .tp-gear { width:22px; height:22px; font-size:12px; }
  .tp-sig svg { width:20px; height:20px; }
  .tp-c { width:28px; height:28px; } .tp-c.st svg { width:16px; height:16px; }
  .tp-badge { height:25px; font-size:11px; padding:0 8px 0 6px; } .tp-badge svg { width:13px; height:13px; }
  .infocard { padding:10px 12px 8px; }
  .ptop { padding:6px 10px; }
  /* 底部控制栏: 手机宽度紧张, 全面紧凑化 */
  .pbar { gap:8px; padding-left:10px; padding-right:10px; }
  .pp { width:38px; height:38px; font-size:14px; }
  .pbar .t { min-width:38px; font-size:12.5px; }
  .spd { padding:8px 11px; font-size:13px; }
  .qbtn { padding:8px 10px; font-size:12.5px; }
}
#gear { background:var(--panel2); border:none; color:var(--muted); font-size:18px; cursor:pointer; border-radius:10px; width:36px; height:32px; }
#gear:hover { color:var(--text); }
#out { background:var(--panel2); border:none; color:var(--muted); font-size:15px; cursor:pointer; border-radius:10px; width:36px; height:32px; }
#out:hover { color:var(--text); }
.grid-wrap { padding:14px 16px 20px; display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:10px; max-width:1180px; margin:0 auto; }
/* 事件卡片: 官方App横排列表 (封面左, 信息右) */
.card { display:flex; gap:12px; align-items:center; background:var(--panel); border-radius:14px; overflow:hidden; cursor:pointer; transition:transform .15s,box-shadow .15s; border:1px solid var(--line); box-shadow:var(--shadow); padding:9px; }
.card:hover { transform:translateY(-2px); }
.thumb { flex:0 0 132px; width:132px; height:76px; border-radius:10px; overflow:hidden; background:#000; position:relative; }
.thumb img { width:100%; height:100%; object-fit:cover; display:block; }
.cnum { position:absolute; right:5px; bottom:5px; background:#000000b8; color:#fff; font-size:10.5px; line-height:1; padding:3px 6px; border-radius:8px; }
.thumb .ph { background:var(--panel2); height:100%; display:flex; align-items:center; justify-content:center; color:var(--muted2); font-size:20px; }
.meta { flex:1; min-width:0; }
.meta .l1 { display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.meta .rt { font-size:13.5px; font-weight:700; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.meta .tm { font-size:12px; color:var(--muted); white-space:nowrap; flex:0 0 auto; font-variant-numeric:tabular-nums; }
.meta .l2 { display:flex; justify-content:space-between; gap:8px; margin-top:4px; font-size:11.5px; color:var(--muted); white-space:nowrap; overflow:hidden; }
.meta .l2 span { overflow:hidden; text-overflow:ellipsis; }
.meta .l2 .sz { flex:0 0 auto; font-variant-numeric:tabular-nums; }
/* 日期分组小标题 (全部日期视图) */
.dhead { grid-column:1/-1; display:flex; align-items:baseline; gap:8px; padding:8px 2px 0; }
.dhead b { font-size:13px; font-weight:700; }
.dhead .n { font-size:11.5px; color:var(--muted2); }
.player { display:none; position:fixed; inset:0; height:100vh; height:100dvh; background:var(--bg); color:var(--text); z-index:100; flex-direction:column; }
/* 播放器子页面跟随全局主题: 卡片/头部/控制栏用变量, 只有视频画面区域保持恒定深色 (--stage), 看片更沉浸 */
.player.open { display:flex; }
.ptop { display:flex; align-items:center; gap:10px; padding:10px 14px; }
.ptop .pdl { margin-left:auto; }
.ptitle { flex:1; min-width:0; text-align:center; font-size:12.5px; font-weight:600; color:var(--muted);
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-variant-numeric:tabular-nums; }
.pback { background:none; border:none; color:var(--text); font-size:16.5px; cursor:pointer; padding:6px 4px; white-space:nowrap; }
.pdl { background:none; border:none; color:var(--text); font-size:19px; cursor:pointer; padding:6px 8px; }
.pscroll { flex:1; min-height:0; overflow-y:auto; -webkit-overflow-scrolling:touch; padding:2px 14px 14px; display:flex; flex-direction:column; gap:12px; }
.pscroll > * { flex:0 0 auto; }
.vwrap { position:relative; border-radius:14px; overflow:hidden; max-width:980px; width:100%; margin:0 auto; background:var(--stage); }
/* 行车遥测面板 (视频上方, Tesla App 样式, 不遮挡画面) */
.tpanel { display:none; background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:14px 18px 10px; max-width:980px; width:100%; margin:0 auto; }
.tpanel.show { display:block; }
.tpanel.folded .tp-rows { display:none; }
/* 无遥测事件(哨兵/停车): 顶部只保留 时间 + 城市·位置 一行, 不留空白块 */
.tpanel.plain { padding:12px 18px; }
.tpanel.plain .tp-mid,
.tpanel.plain .tp-fold,
.tpanel.plain .tp-rows,
.tpanel.plain .tp-tr { display:none; }
.infocard.plain .ic-time { display:none; }
.infocard.plain .ic-badge { margin-left:0; }
.tp-top { display:flex; justify-content:space-between; align-items:center; }
.tp-l { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }
.tp-date { font-size:13.5px; color:var(--text); font-variant-numeric:tabular-nums; }
.tp-loc { font-size:12.5px; color:var(--muted); }
/* 哨兵/纪念事件: 触发画面摄像头 (来自 event.json 的 camera 字段) */
.tp-tag { display:none; align-items:center; gap:4px; height:22px; padding:0 9px; border-radius:11px;
  background:var(--amberbg); color:var(--amber); font-size:11.5px; font-weight:600;
  border:1px solid var(--amberline); white-space:nowrap; align-self:center; }
.tp-tag.show { display:inline-flex; }
.tp-tag b { color:var(--amberb); font-weight:800; font-variant-numeric:tabular-nums; }
.tp-tr { display:flex; align-items:center; gap:6px; }
/* 转向灯: 矢量箭头(圆角方块底 + 白色箭头), 不用 ⬅➡ emoji —— emoji 是彩色字形,
   不认 CSS color, 点亮时颜色不会变, 看起来永远像"静止的图标" */
.tp-sig { display:inline-flex; align-items:center; color:var(--muted2); line-height:1; opacity:.5; }
.tp-sig svg { width:23px; height:23px; display:block; }
.tp-sig.on { color:#f59e0b; opacity:1; animation:tpBlink 1.15s steps(1,end) infinite; }
@keyframes tpBlink { 0%, 52% { opacity:1 } 53%, 100% { opacity:.18 } }
@media (prefers-reduced-motion: reduce) { .tp-sig.on { animation:none } }
.tp-gear { background:#34c759; color:#fff; font-weight:800; font-size:14px; width:26px; height:26px;
  border-radius:50%; display:inline-flex; align-items:center; justify-content:center; }
.tp-mid { display:flex; align-items:center; margin-top:8px; }
.tp-spd { font-size:34px; font-weight:800; color:var(--text); line-height:1.1; font-variant-numeric:tabular-nums; }
.tp-unit { font-size:13px; color:var(--muted); font-weight:600; margin-left:6px; }
.tp-badges { display:flex; align-items:center; gap:10px; margin-left:auto; }
.tp-c { width:34px; height:34px; border-radius:50%; display:inline-flex; align-items:center;
  justify-content:center; font-size:11.5px; font-weight:700; flex:none; }
.tp-c.t { background:var(--panel2); color:var(--text); font-size:15px; }
.tp-badge { display:inline-flex; align-items:center; gap:5px; height:30px; padding:0 11px 0 8px;
  border-radius:15px; font-size:12.5px; font-weight:700; font-variant-numeric:tabular-nums; flex:none; }
.tp-badge svg { width:16px; height:16px; flex:none; }
.tp-badge.thr { background:#1f7ae0; color:#fff; }
.tp-badge.brk { background:var(--panel2); color:var(--muted); }
.tp-badge.brk.on { background:#ff453a; color:#fff; box-shadow:0 0 9px #ff453a66; }
.tp-c.st { background:var(--panel2); color:var(--muted); }
.tp-c.st svg { width:20px; height:20px; transition:transform .18s ease-out; }
/* 自动驾驶状态直接挂在方向盘这颗图标上 (AP/EAP/FSD 共用):
   启动时蓝色 (与车机上 AP 图标同色), 未启动时灰底, 不再额外占一个 "AP" 徽标 */
.tp-c.st.ap-on { background:linear-gradient(135deg,#2f7cf6,#1d5fd0); color:#fff;
  box-shadow:0 0 10px #2f7cf655; }
.tp-fold { display:block; margin:8px 0 0 auto; background:none; border:none; color:var(--muted);
  font-size:12px; cursor:pointer; padding:4px 2px; }
.tp-rows { border-top:1px solid var(--line); margin-top:2px; padding-top:8px; display:grid;
  grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:1px 20px; }
.tp-rows div { color:var(--text); font-size:13px; padding:3px 0; font-variant-numeric:tabular-nums; }
.tp-rows .k { color:var(--muted); margin-right:9px; }
.vgrid { display:grid; gap:3px; background:var(--stage); }
.vcell { position:relative; overflow:hidden; background:var(--stage); cursor:zoom-in; aspect-ratio:16/9; }
.vcell.focused { grid-column:1/-1; grid-row:1/-1; cursor:zoom-out; }
/* 单路: 格子高度由 JS 按画面真实比例算 (4:3 片源不裁上下), 关掉 16/9 的 CSS 约束 */
.vgrid.one .vcell { aspect-ratio:auto; }
.vcell video { width:100%; height:100%; background:var(--stage); object-fit:cover; display:block; }
/* 以下是叠在视频画面上的浮层, 永远在深色画面上, 用固定颜色 */
.startmask { position:absolute; inset:0; z-index:5; background:rgba(0,0,0,.55); color:#fff; font-size:16px; display:none; align-items:center; justify-content:center; cursor:pointer; letter-spacing:1px; }
.startmask.show { display:flex; }
.vcell .clabel { position:absolute; right:7px; bottom:7px; font-size:11px; color:#e8eef4; background:rgba(20,24,29,.72); border-radius:6px; padding:2px 7px; pointer-events:none; }
.vcell .cload { position:absolute; left:0; top:0; right:0; bottom:0; display:flex; align-items:center; justify-content:center; gap:7px; font-size:12.5px; color:#c6cdd4; background:rgba(10,13,18,.6); pointer-events:none; }
.vcell .cload.err { color:#ff6b66; }
.vcell .cload .spin { width:14px; height:14px; border:2px solid #3a4450; border-top-color:#10b981; border-radius:50%; animation:cspin .8s linear infinite; }
@keyframes cspin { to { transform:rotate(360deg); } }
.infocard { background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:14px 16px 10px; max-width:980px; width:100%; margin:0 auto; box-shadow:var(--shadow); }
.ic-top { display:flex; align-items:center; gap:10px; }
.ic-time { font-size:14px; color:var(--text); }
.ic-badge { margin-left:auto; background:#3b82f6; color:#fff; font-size:12px; font-weight:600; border-radius:14px; padding:3px 12px; }
.ic-mid { display:flex; align-items:baseline; gap:12px; margin:10px 0 2px; flex-wrap:wrap; }
.ic-big { font-size:30px; font-weight:700; letter-spacing:.5px; color:var(--text); }
.ic-sub { font-size:12.5px; color:var(--muted); }
/* 画面选择条: 默认单路(触发画面), 点其他路/全览才加载对应视频 */
.cambar { display:none; gap:6px; flex-wrap:wrap; justify-content:center; max-width:980px; width:100%; margin:0 auto; }
.cambar.show { display:flex; }
.cambar button { background:var(--panel2); color:var(--muted); border:1px solid var(--line2); border-radius:8px;
  font-size:12.5px; padding:8px 12px; cursor:pointer; }
.cambar button.on { background:var(--blue); border-color:var(--blue); color:#fff; }
/* 触发摄像头那一路: 与片段芯片一致的红点标记 */
.cambar button.trig::before { content:''; display:inline-block; width:5px; height:5px; border-radius:50%;
  background:#ff453a; margin-right:5px; vertical-align:1px; }
.cambar button.trig.on::before { background:#fff; }
.clipbar { display:none; gap:6px; flex-wrap:wrap; margin-top:9px; }
.clipbar.show { display:flex; }
.clipbar button { background:var(--panel2); color:var(--muted); border:1px solid var(--line2); border-radius:8px;
  font-size:12px; padding:9px 11px; cursor:pointer; font-variant-numeric:tabular-nums; }
.clipbar button.on { background:var(--blue); border-color:var(--blue); color:#fff; }
/* 含触发时刻的那一段: 前面点个小圆点, 窄屏也不额外占宽度 */
.clipbar button.trig::before { content:''; display:inline-block; width:5px; height:5px; border-radius:50%;
  background:#ff453a; margin-right:5px; vertical-align:1px; }
.clipbar button.trig.on::before { background:#fff; }
.ic-rows { display:none; font-size:12.5px; line-height:1.9; color:var(--muted); word-break:break-all; border-top:1px solid var(--line); margin-top:8px; padding-top:8px; }
.ic-rows.open { display:block; }
.ick { display:inline-block; min-width:64px; color:var(--muted); }
.ic-fold { background:none; border:none; color:var(--muted); font-size:12px; cursor:pointer; padding:10px 2px 6px; margin-left:auto; display:block; }
.pbar { display:flex; align-items:center; gap:12px; flex-wrap:wrap; padding:10px 16px calc(12px + env(safe-area-inset-bottom,0px)); max-width:1008px; margin:0 auto; width:100%; box-sizing:border-box; }
.pp { width:44px; height:44px; border-radius:50%; background:var(--text); color:var(--panel); border:none; font-size:16px; cursor:pointer; flex:0 0 auto; }
.pbar input[type=range] { flex:1; accent-color:#3b82f6; min-width:80px; }
.pbar .t { font-size:13.5px; color:var(--text); min-width:44px; text-align:center; }
.spd { background:#3b82f6; color:#fff; border:none; border-radius:10px; padding:9px 15px; font-size:14px; font-weight:600; cursor:pointer; flex:0 0 auto; }
.qsel { position:relative; flex:0 0 auto; }
.qbtn { background:var(--panel2); color:var(--muted); border:1px solid var(--line2); border-radius:10px; padding:9px 12px; font-size:13px; font-weight:600; cursor:pointer; white-space:nowrap; }
.qbtn.on { background:#10b981; border-color:#10b981; color:#fff; }
.qmenu { display:none; position:absolute; right:0; bottom:calc(100% + 6px); background:var(--panel); border:1px solid var(--line2); border-radius:10px; padding:4px; min-width:96px; box-shadow:0 8px 22px #00000040; z-index:30; }
.qsel.open .qmenu { display:block; }
.qmenu button { display:block; width:100%; text-align:left; background:none; border:none; color:var(--text); font-size:13px; padding:9px 12px; border-radius:7px; cursor:pointer; white-space:nowrap; }
.qmenu button.on { background:#10b981; color:#fff; }
/* 转码/加载提示: 单独占一整行 (以前是 pbar 里的 flex:0 0 100%, 而 pbar 不换行,
   结果被挤到屏幕右侧外面, 手机上只露出「正在…」半个字) */
.qhint { font-size:12px; color:var(--amber); flex:1 0 100%; min-width:0; text-align:center;
  line-height:1.5; display:none; word-break:break-word; }
.empty { text-align:center; padding:80px 20px; color:var(--muted2); }
.empty .big { font-size:44px; margin-bottom:14px; }
/* 设置面板 */
.mask { display:none; position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:200; }
.mask.open { display:block; }
.panel { position:fixed; top:50%; left:50%; transform:translate(-50%,-50%); width:min(560px,94vw); max-height:86vh; overflow:auto; background:var(--panel); border-radius:14px; z-index:201; padding:18px; display:none; box-shadow:0 12px 40px #00000040; }
.panel.open { display:block; }
.panel h2 { font-size:15px; margin-bottom:12px; display:flex; align-items:center; }
.panel h2 .x { margin-left:auto; background:none; border:none; color:var(--muted); font-size:20px; cursor:pointer; padding:4px 8px; }
.stabs { display:flex; gap:8px; margin-bottom:14px; flex-wrap:wrap; }
.stab { flex:0 1 calc(33.333% - 6px); min-width:0; padding:10px 4px; border-radius:10px; background:var(--panel2); color:var(--muted); text-align:center; cursor:pointer; font-size:12.5px; border:none; white-space:nowrap; }
.stab.active { background:var(--accent); color:#fff; }
.langgrid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px; }
.langgrid button { padding:10px 6px; border-radius:10px; background:var(--panel2); border:1px solid var(--line2);
  color:var(--text); font-size:13px; cursor:pointer; text-align:center; line-height:1.35; }
.langgrid button .code { display:block; font-size:10.5px; color:var(--muted2); margin-top:2px; letter-spacing:.5px; }
.langgrid button.on { border-color:var(--accent); box-shadow:0 0 0 2px var(--accent) inset; color:var(--accent); }
.langgrid button.on .code { color:var(--accent); opacity:.8; }
.hint { font-size:11.5px; color:var(--muted2); line-height:1.6; margin-bottom:10px; }
/* 飞书推送 */
.ninput { display:block; width:100%; box-sizing:border-box; margin-bottom:8px; padding:9px 11px; border-radius:9px;
  background:var(--panel2); border:1px solid var(--line2); color:var(--text); font-size:12.5px; outline:none; }
.ninput:focus { border-color:var(--accent); }
.nrow { display:flex; align-items:center; gap:8px; margin-bottom:8px; font-size:13px; color:var(--text); }
.nrow > span:first-child { flex:0 0 auto; }
.nrow input[type=checkbox] { width:18px; height:18px; accent-color:var(--accent); margin-left:auto; }
.ninput.num { width:76px; margin:0; text-align:center; }
.ninput.masked { color:var(--muted2); letter-spacing:1.5px; cursor:default; border-style:dashed; }
select.ninput { cursor:pointer; }
.eyebar { display:flex; align-items:center; gap:8px; margin:0 0 8px; }
.eyebar .lbl { flex:1; font-size:11.5px; color:var(--muted2); }
.eyebar .mini { flex:0 0 auto; padding:6px 12px; border-radius:8px; background:var(--panel2);
  border:1px solid var(--line2); color:var(--text); font-size:12px; cursor:pointer; }
.eyebar .mini:hover { border-color:var(--accent); }
.hint2 { font-size:11.5px; color:var(--muted2); }
/* 系统更新 (OTA) */
.updrow { display:flex; align-items:baseline; gap:8px; padding:7px 0; font-size:13px; }
.updk { color:var(--muted); min-width:64px; flex:0 0 auto; }
.updtag { font-size:11px; padding:1px 8px; border-radius:9px; background:var(--amberbg); color:var(--amber); border:1px solid var(--amberline); white-space:nowrap; }
.updtag.new { background:rgba(232,68,63,.14); color:var(--accent); border-color:rgba(232,68,63,.32); }
.updnotes { display:none; background:var(--panel2); border-radius:10px; padding:9px 12px; font-size:12.5px; line-height:1.85; color:var(--muted); margin:6px 0 2px; }
/* 自动更新开关: 一行 + 右侧勾选框, 默认勾上 */
.updauto { display:flex; align-items:center; gap:8px; margin:10px 0 2px; padding-top:10px;
  border-top:1px solid var(--line); font-size:13px; color:var(--text); cursor:pointer; }
.updauto span { flex:1; }
.updauto input[type=checkbox] { width:18px; height:18px; margin:0; accent-color:var(--accent); cursor:pointer; }
.updbtns { display:flex; gap:8px; margin:10px 0 8px; }
.updbtns .mini { flex:1; padding:9px 0; border-radius:9px; background:var(--panel2); border:none; color:var(--text); font-size:13px; cursor:pointer; }
.updbtns .mini.logout { background:transparent; border:1px solid var(--accent); color:var(--accent); }
.updbtns .mini.primary { background:var(--accent); color:#fff; }
.updbtns .mini:disabled { opacity:.45; cursor:default; }
#gear { position:relative; }
#gear.hasupd::after { content:''; position:absolute; top:4px; right:4px; width:7px; height:7px; border-radius:50%; background:var(--accent); box-shadow:0 0 0 2px var(--headbg); }
.upbtn { display:block; width:100%; padding:10px; border:1px dashed var(--line2); border-radius:10px; color:var(--muted); text-align:center; cursor:pointer; font-size:13px; margin-bottom:12px; background:var(--panel2); }
.upbtn:hover { border-color:var(--accent); color:var(--text); }
.item { display:flex; align-items:center; gap:10px; background:var(--panel2); border-radius:10px; padding:9px 12px; margin-bottom:8px; font-size:13px; }
.item .n { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.item button { background:var(--panel2); border:1px solid var(--line2); color:var(--muted); border-radius:7px; padding:5px 10px; font-size:12px; cursor:pointer; }
.item button.danger:hover { background:var(--accent); border-color:var(--accent); color:#fff; }
.item button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
/* 文件管理器: 多选与批量操作 */
.item .fm-chk { width:17px; height:17px; flex:0 0 auto; accent-color:var(--accent); cursor:pointer; }
.item.fm-sel { box-shadow:inset 0 0 0 1px var(--accent); }
.item .fm-mini { padding:7px 10px; min-height:32px; min-width:32px; }
.fm-bar { background:var(--panel2); border:1px solid var(--line2); border-radius:10px; padding:10px; margin-bottom:10px; }
.fm-bar .row { display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
.fm-bar button { background:var(--panel2); border:1px solid var(--line2); color:var(--text); border-radius:8px; padding:7px 10px; font-size:12px; cursor:pointer; }
.fm-bar button:hover { border-color:var(--accent); color:var(--accent); }
.fm-bar button.fm-danger { color:var(--accent); border-color:var(--accent); }
.fm-bar button.fm-go { background:var(--accent); border-color:var(--accent); color:#fff; }
.fm-bar button.fm-go:hover { color:#fff; }
.fm-bar .fm-dest-input { flex:1; min-width:130px; background:var(--bg); border:1px solid var(--line2); border-radius:8px; color:var(--text); padding:7px 9px; font-size:12px; outline:none; }
.fm-count { font-size:12px; color:var(--muted); }
.fm-purge { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:0 0 10px; }
.fm-purge button { background:transparent; border:1px solid var(--accent); color:var(--accent); border-radius:8px; padding:8px 12px; font-size:12.5px; cursor:pointer; white-space:nowrap; }
.fm-purge button:hover { background:var(--accent); color:#fff; }
.fm-purge .hint { flex:1; min-width:170px; margin:0; }
.item .tag { font-size:10.5px; color:#4cc38a; }
.toast { position:fixed; bottom:24px; left:50%; transform:translateX(-50%); background:var(--accent); color:#fff; padding:9px 20px; border-radius:20px; font-size:13px; z-index:300; display:none; }
.expp { display:none; position:fixed; right:14px; bottom:70px; width:min(320px,92vw); background:var(--panel); border:1px solid var(--line2); border-radius:14px; padding:14px; z-index:150; box-shadow:0 10px 30px #00000060; }
.expp.open { display:block; }
.expp .expt { font-size:13.5px; font-weight:600; margin-bottom:10px; display:flex; align-items:center; }
.expp .expt .x { margin-left:auto; background:none; border:none; color:var(--muted); font-size:17px; cursor:pointer; }
.expitem { display:flex; align-items:center; gap:8px; padding:7px 4px; font-size:13px; color:var(--text); cursor:pointer; }
.expitem input { accent-color:var(--accent); width:16px; height:16px; }
.expr { display:flex; gap:8px; margin-top:10px; flex-wrap:wrap; }
.expr .mini { flex:1 1 30%; padding:7px 0; border-radius:9px; background:var(--panel2); border:none; color:var(--text); font-size:12.5px; cursor:pointer; }
.expr .mini.primary { background:var(--accent); color:#fff; }
.stitch { display:none; position:fixed; inset:0; background:rgba(0,0,0,.72); z-index:260; align-items:center; justify-content:center; }
.stitch.open { display:flex; }
.stbox { width:min(340px,88vw); background:var(--panel); border-radius:16px; padding:20px 20px 16px; box-shadow:0 12px 40px #000c; text-align:center; }
.stt { font-size:14.5px; font-weight:600; margin-bottom:14px; }
.stbar { height:8px; border-radius:5px; background:var(--line2); overflow:hidden; }
.stfill { height:100%; width:0; background:linear-gradient(90deg,#3b82f6,#60a5fa); border-radius:5px; transition:width .4s; }
.stpct { font-size:13px; color:var(--muted); margin-top:8px; }
.sthint { font-size:11.5px; color:var(--muted2); margin-top:4px; line-height:1.5; }
/* 实时预览: 与其它三个分类页签同级, 内容直接排在页签下方 (不再是全屏浮层 + 返回按钮) */
.livep { display:none; max-width:1180px; margin:0 auto; padding:12px 16px 24px; }
.livep.open { display:block; }
body.livemode #filters, body.livemode #dfilters, body.livemode #dpick,
body.livemode #grid, body.livemode #empty { display:none !important; }
.lvtop { display:flex; align-items:center; gap:10px; padding:0 0 10px; border-bottom:1px solid var(--line); }
.lvtitle { font-weight:600; font-size:14.5px; flex:1; min-width:0; line-height:1.35; }
.lvtitle small { display:inline; font-size:12px; font-weight:400; margin-left:6px; }
.lvstatus { font-size:12px; color:var(--muted); text-align:right; max-width:42%; line-height:1.4; word-break:break-all; }
.lvbody { padding:12px 0 0; display:flex; flex-direction:column; gap:10px; }
.lvmeta { font-size:13px; color:var(--muted); }
/* 单路: 宽高由 JS 按片源真实比例定 (Tesla 多为 4:3), 上限 58vh 且居中,
   不写死 16/9, 也不靠 max-height 把画面压扁 */
#lv-video { display:block; width:100%; height:auto; max-height:58vh; margin:0 auto;
  background:#000; border-radius:12px; object-fit:contain; }
/* 全览: 4 路同屏。拿不到片源比例前先用 16/9 撑住格子, JS 算好真实行高后
   加 .ready 去掉这个约束, 避免 CSS aspect-ratio 压过 grid 行高把 4:3 裁掉 */
.lvgrid { display:none; gap:3px; background:#000; border-radius:12px; overflow:hidden; grid-template-columns:1fr 1fr; }
.lvgrid.on { display:grid; }
.lvgrid.n1 { grid-template-columns:1fr; }
.lvgrid .lvcell { position:relative; overflow:hidden; background:#000; aspect-ratio:16/9; cursor:zoom-in; }
.lvgrid.ready .lvcell { aspect-ratio:auto; }
.lvgrid .lvcell video { width:100%; height:100%; object-fit:contain; display:block; background:#000; }
.lvgrid .lvcell .clabel { position:absolute; right:6px; bottom:6px; font-size:11px; color:#e8eef4; background:rgba(20,24,29,.72); border-radius:6px; padding:2px 7px; pointer-events:none; }
.lvrow { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.lvbtn { padding:9px 14px; border-radius:9px; border:1px solid var(--line2); background:var(--panel2); color:var(--text); font-size:13px; cursor:pointer; }
.lvbtn.on { background:var(--accent); color:#fff; border-color:var(--accent); }
.lvrow select { padding:9px 10px; border-radius:9px; border:1px solid var(--line2); background:var(--panel2); color:var(--text); font-size:13px; }
.lvbody > .hint { margin-top:2px; margin-bottom:0; }
@media (max-width:640px){ .expp { left:50%; right:auto; transform:translateX(-50%); bottom:78px; } }
/* 设备与存储: 与四套界面风格共用颜色、边框和控件语义 */
.storage-card { background:var(--panel2); border:1px solid var(--line); border-radius:12px;
  padding:12px; margin-bottom:10px; color:var(--text); }
.storage-head { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:8px; }
.storage-btn { background:var(--panel); border:1px solid var(--line2); color:var(--text);
  border-radius:8px; padding:5px 12px; font-size:12px; cursor:pointer; }
.storage-btn:hover { border-color:var(--accent); color:var(--accent); }
.storage-disk { border-top:1px solid var(--line); padding-top:8px; margin-top:8px; font-size:12px; }
.storage-part { display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:6px 0; font-size:12px; }
.storage-part-name { min-width:170px; color:var(--text); }
.storage-current { color:var(--blue); font-weight:600; }
.storage-ok { color:var(--blue); font-weight:600; }
.storage-warn { color:var(--amber); font-weight:600; }
.storage-meta { color:var(--muted2); }
.storage-mount { color:var(--muted2); }
.storage-use { background:var(--blue); border:1px solid var(--blue); color:#fff; border-radius:7px;
  padding:4px 12px; font-size:12px; cursor:pointer; }
.storage-format { background:transparent; border:1px solid var(--accent); color:var(--accent);
  border-radius:7px; padding:4px 12px; font-size:12px; cursor:pointer; }
.storage-alloc { border-top:1px solid var(--line); margin-top:10px; padding-top:10px; }
.storage-danger { color:var(--accent); font-weight:400; }
.storage-form-row { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:8px; font-size:12px; }
.storage-select { flex:1; min-width:220px; background:var(--panel); color:var(--text);
  border:1px solid var(--line2); border-radius:8px; padding:7px 9px; max-width:100%; }
.storage-select:focus { border-color:var(--accent); outline:2px solid var(--accent); outline-offset:1px; }
.storage-slider-row { display:flex; align-items:center; gap:10px; margin-top:10px; font-size:12px; }
.storage-range { flex:1; min-width:120px; accent-color:var(--accent); cursor:pointer; }
.storage-percent { min-width:42px; color:var(--text); font-weight:700; text-align:right; }
.storage-calc { margin-top:8px; padding:8px 10px; background:var(--panel); border:1px solid var(--line);
  border-radius:8px; color:var(--muted); }
.storage-calc b { color:var(--text); }
.storage-init { background:var(--accent); border:1px solid var(--accent); color:#fff; border-radius:8px;
  padding:7px 14px; font-size:12px; cursor:pointer; margin-top:8px; }
.storage-format:disabled, .storage-init:disabled { opacity:.45; cursor:not-allowed; }
html[data-style="apple"] .storage-card { border-radius:16px; border-color:transparent; box-shadow:0 4px 18px #0000000a; }
html[data-style="apple"] .storage-select,
html[data-style="apple"] .storage-btn,
html[data-style="apple"] .storage-init { border-radius:10px; }
html[data-style="claude"] .storage-card { border-radius:12px; box-shadow:none; }
html[data-style="pixel"] .storage-card { border:2px solid var(--line); box-shadow:4px 4px 0 var(--pxshadow); }
html[data-style="pixel"] .storage-btn,
html[data-style="pixel"] .storage-use,
html[data-style="pixel"] .storage-format,
html[data-style="pixel"] .storage-init,
html[data-style="pixel"] .storage-calc { border:2px solid var(--line); }
html[data-style="pixel"] .storage-init { border-color:var(--accent); box-shadow:3px 3px 0 var(--pxshadow); }
/* ===== 可选界面风格: 默认 / Apple / Claude / 像素 =====
   只覆盖颜色、圆角、阴影与少量排版, 不改布局与 DOM, 与深/浅色主题正交。
   放在基础样式之后, 保证同名选择器 (如 .tab.active) 能盖过默认规则。 */
html[data-style="apple"] {
  --bg:#f5f5f7; --headbg:rgba(255,255,255,.78); --panel:#ffffff; --panel2:#f0f0f2; --chipbg:#ffffff;
  --line:#e6e6eb; --line2:#d6d6dc; --text:#1d1d1f; --muted:#6e6e73; --muted2:#86868b;
  --accent:#ff3b30; --blue:#0071e3; --shadow:0 1px 2px #00000008, 0 10px 28px #0000000f; --headline:#00000000;
}
html[data-style="apple"][data-theme="dark"] {
  --bg:#000000; --headbg:rgba(28,28,30,.78); --panel:#1c1c1e; --panel2:#2c2c2e; --chipbg:#1c1c1e;
  --line:#2c2c2e; --line2:#3a3a3c; --text:#f5f5f7; --muted:#a1a1a6; --muted2:#8e8e93;
  --accent:#ff453a; --blue:#0a84ff; --shadow:0 10px 28px #00000066; --headline:#ffffff00;
}
html[data-style="claude"] {
  --bg:#faf9f5; --headbg:rgba(250,249,245,.86); --panel:#ffffff; --panel2:#f2efe7; --chipbg:#fffdf8;
  --line:#e8e3d7; --line2:#ddd6c8; --text:#1f1e1d; --muted:#6b6862; --muted2:#8a857c;
  --accent:#c96442; --blue:#b8563a; --shadow:0 1px 0 #00000006; --headline:#00000000;
}
html[data-style="claude"][data-theme="dark"] {
  --bg:#1f1e1d; --headbg:rgba(31,30,29,.86); --panel:#262521; --panel2:#302e29; --chipbg:#262521;
  --line:#35322c; --line2:#423e36; --text:#f0eee6; --muted:#a8a49a; --muted2:#8f8b81;
  --accent:#d97757; --blue:#d97757; --shadow:none; --headline:#ffffff00;
}
html[data-style="apple"] header,
html[data-style="claude"] header {
  box-shadow:none; border-bottom:1px solid var(--line);
  backdrop-filter:saturate(180%) blur(18px); -webkit-backdrop-filter:saturate(180%) blur(18px);
}
html[data-style="apple"] header h1 { font-weight:600; letter-spacing:-.2px; }
html[data-style="apple"] .card { border-color:transparent; border-radius:18px;
  box-shadow:0 1px 2px #0000000a, 0 8px 24px #0000000d; }
html[data-style="apple"] .card:hover { transform:translateY(-2px); box-shadow:0 2px 4px #0000000d, 0 14px 34px #00000014; }
html[data-style="apple"] .thumb { border-radius:12px; }
html[data-style="apple"] .storcard { border-radius:18px; border-color:transparent; }
html[data-style="apple"] .syscell { border-radius:10px; border-color:transparent; }
html[data-style="apple"] .chip { border-radius:999px; background:#fff; box-shadow:0 .5px 1px #0000000a; }
html[data-style="apple"] .chip.on { background:var(--blue); box-shadow:none; }
/* 页签做成 iOS 分段控件: 灰槽里浮起一块白色选中块, 而不是深色药丸 */
html[data-style="apple"] .tab { border-radius:999px; background:#e9e9ec; color:#6e6e73; }
html[data-style="apple"] .tab:hover { color:#1d1d1f; }
html[data-style="apple"] .tab.active { background:#fff; color:#1d1d1f;
  box-shadow:0 .5px 2px #0000001f, 0 0 0 .5px #0000000a; }
html[data-style="apple"][data-theme="dark"] .tab { background:#1c1c1e; color:#a1a1a6; }
html[data-style="apple"][data-theme="dark"] .tab.active { background:#3a3a3c; color:#fff;
  box-shadow:0 1px 3px #00000066; }
html[data-style="apple"] .panel { border-radius:20px; box-shadow:0 24px 80px #00000033; }
html[data-style="apple"] .upbtn { border-radius:14px; }
html[data-style="claude"] header h1 { font-weight:600; letter-spacing:.1px; }
html[data-style="claude"] .card { border-radius:14px; box-shadow:none; border-color:var(--line); }
html[data-style="claude"] .card:hover { transform:none; box-shadow:0 2px 10px #00000009; }
html[data-style="claude"] .storcard { border-radius:14px; box-shadow:none; }
html[data-style="claude"] .syscell { border-radius:9px; border-color:transparent; background:var(--panel2); }
html[data-style="claude"] .chip { border-radius:11px; }
html[data-style="claude"] .chip.on { border-color:var(--blue); }
html[data-style="claude"] .tab { border-radius:10px; }
html[data-style="claude"] .panel { border-radius:16px; border:1px solid var(--line); box-shadow:0 20px 60px #00000026; }
html[data-style="claude"] .upbtn { border-radius:11px; }
html[data-style="claude"] .storbar { border-radius:3px; }
html[data-style="claude"] .toast { border-radius:12px; }
/* 界面风格选择卡 (设置 → 网页背景 顶部) */
.stylepick { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin:9px 0 14px; }
.stylepick button { position:relative; padding:9px 9px 8px; border-radius:12px; border:1.5px solid var(--line);
  background:var(--panel2); color:var(--text); cursor:pointer; text-align:left;
  font-size:12.5px; font-weight:600; line-height:1.2; transition:border-color .15s,background .15s; }
.stylepick button:hover { border-color:var(--muted2); }
.stylepick button.on { border-color:var(--blue); background:var(--chipbg); }
.stylepick button.on::after { content:'✓'; position:absolute; right:7px; top:6px; font-size:11px;
  color:#fff; background:var(--blue); width:15px; height:15px; line-height:15px; border-radius:50%;
  text-align:center; font-weight:700; }
.stylepick .sw { display:flex; gap:3px; margin-bottom:7px; }
.stylepick .sw i { display:block; height:16px; flex:1; border-radius:4px; border:1px solid #00000012; }
@media (max-width:520px){ .stylepick { grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px; }
  .stylepick button { padding:8px 7px; font-size:12px; } }
/* 标题与图标 (设置 → 品牌) */
.brandbox { display:flex; align-items:center; gap:12px; padding:12px; margin-bottom:12px;
  border:1px solid var(--line); border-radius:12px; background:var(--panel2); }
.brandbox .blogo { width:52px; height:52px; border-radius:50%; object-fit:cover; flex:0 0 auto;
  background:var(--panel); box-shadow:0 0 0 1px var(--line); }
.brandmeta { display:flex; flex-direction:column; gap:4px; min-width:0; }
.brandmeta b { font-size:15px; color:var(--text); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.brandmeta span { font-size:11.5px; color:var(--muted2); }
.brandrow { display:flex; gap:8px; margin-bottom:12px; }
.brandrow .ninput { margin:0; flex:1; padding:10px 12px; }
.brandrow button { flex:0 0 auto; padding:0 20px; border-radius:9px; border:1px solid var(--accent);
  background:var(--accent); color:#fff; font-size:13px; font-weight:600; cursor:pointer; white-space:nowrap; }
.brandrow button:hover { filter:brightness(1.07); }
.brandreset { padding:9px 14px; border-radius:9px; border:1px solid var(--line2); background:var(--panel2);
  color:var(--muted); font-size:12.5px; cursor:pointer; }
.brandreset:hover { border-color:var(--accent); color:var(--accent); }
html[data-style="pixel"] .brandbox .blogo { border-radius:0; box-shadow:none; border:2px solid var(--line); }
/* ===== 像素艺术风 (Pixel Art) =====
   参考 StyleKit pixel-art: 零圆角 / 2px 硬边框 / 4px 硬偏移阴影 / 8-bit 调色板。
   灵魂是「没有过渡」—— 像素游戏是状态机不是动画引擎, hover 直接换色、按下真的陷进去,
   所以这里统一 transition:none, 用调色板替换代替淡入淡出。 */
html[data-style="pixel"] {
  color-scheme: dark;
  --bg:#1a1c2c; --headbg:#1a1c2c; --panel:#242947; --panel2:#2d3355; --chipbg:#242947;
  --line:#414a78; --line2:#525c8f; --text:#f2f3f7; --muted:#a6abcc; --muted2:#8f95bb;
  --accent:#ff004d; --blue:#29adff; --shadow:4px 4px 0 #0a0b12; --headline:#00000000;
  --pxshadow:#0a0b12; --pxhi:#ffec27; --pxink:#1a1c2c; --pxdot:#2b3152;
  --amberbg:rgba(255,236,39,.16); --amber:#ffec27; --amberb:#ffec27; --amberline:#ffec27;
}
/* 浅色: 纸白面板 + 深靛硬边框, 像 8-bit 游戏说明书; 蓝在浅底上要压深一档才够对比 */
html[data-style="pixel"][data-theme="light"] {
  color-scheme: light;
  --bg:#f4f4f4; --headbg:#ffffff; --panel:#ffffff; --panel2:#f2f2f4; --chipbg:#ffffff;
  --line:#1a1c2c; --line2:#1a1c2c; --text:#1a1c2c; --muted:#5c6284; --muted2:#767c9c;
  --accent:#ff004d; --blue:#0074c9; --shadow:4px 4px 0 #1a1c2c; --headline:#00000000;
  --pxshadow:#1a1c2c; --pxhi:#ffec27; --pxink:#1a1c2c; --pxdot:#dfe1ea;
  --amberbg:rgba(255,236,39,.42); --amber:#7a5f00; --amberb:#5c4700; --amberline:#c2a000;
}
/* 零圆角 + 零过渡, 一刀切掉所有柔和感 */
html[data-style="pixel"] *, html[data-style="pixel"] *::before, html[data-style="pixel"] *::after {
  border-radius:0 !important; transition:none !important;
}
/* 正文用等宽字体撑像素感; 有 Press Start 2P 就用, 没有就退到等宽 (不联网拉字体) */
html[data-style="pixel"] body {
  font-family:'Press Start 2P','Silkscreen',ui-monospace,'Cascadia Mono',Consolas,'Courier New',monospace;
  letter-spacing:.15px;
  background-image:radial-gradient(var(--pxdot) 1px, transparent 1px);
  background-size:8px 8px;
}
/* 顶栏: 深底 + 一条像素红下边框 (Pixel Nav 的做法) */
html[data-style="pixel"] header { border-bottom:3px solid var(--accent); box-shadow:none; }
html[data-style="pixel"] header h1 { font-weight:700; letter-spacing:1px; }
html[data-style="pixel"] header h1 .blogo { border-radius:0; box-shadow:none; border:2px solid var(--line); }
/* 面板/卡片: 2px 硬边框 + 4px 硬偏移阴影, 没有模糊 */
html[data-style="pixel"] .card,
html[data-style="pixel"] .storcard,
html[data-style="pixel"] .panel,
html[data-style="pixel"] .expp,
html[data-style="pixel"] .upbtn,
html[data-style="pixel"] .toast { border:2px solid var(--line); }
html[data-style="pixel"] .card,
html[data-style="pixel"] .storcard,
html[data-style="pixel"] .panel,
html[data-style="pixel"] .expp,
html[data-style="pixel"] .upbtn { box-shadow:4px 4px 0 var(--pxshadow); }
html[data-style="pixel"] .card:hover { transform:none; border-color:var(--accent); box-shadow:4px 4px 0 var(--accent); }
html[data-style="pixel"] .thumb { border:2px solid var(--line); }
/* 页签: 方块按键盘, 选中项用像素黄 (街机菜单语义) */
html[data-style="pixel"] .tab { border:2px solid var(--line); background:var(--panel2); color:var(--muted); font-weight:700; }
html[data-style="pixel"] .tab:hover { color:var(--text); border-color:var(--blue); }
html[data-style="pixel"] .tab.active { background:var(--pxhi); color:var(--pxink); border-color:var(--pxink); box-shadow:3px 3px 0 var(--pxshadow); }
/* 筛选胶囊: 选中 = 像素红, hover 换像素蓝 */
html[data-style="pixel"] .chip { border:2px solid var(--line); background:var(--chipbg); font-weight:600; }
html[data-style="pixel"] .chip:hover { border-color:var(--blue); color:var(--text); }
html[data-style="pixel"] .chip.on { background:var(--accent); border-color:var(--pxshadow); color:#fff; box-shadow:2px 2px 0 var(--pxshadow); }
/* 存储条: 加粗成血条 (HP bar) */
html[data-style="pixel"] .storbar { height:9px; border:2px solid var(--line); background:var(--panel2); margin-right:26px; }
html[data-style="pixel"] .storbar i { border-radius:0 !important; }
html[data-style="pixel"] .syscell { border:2px solid var(--line); background:var(--panel2); }
html[data-style="pixel"] .upbtn { border-style:solid; }
html[data-style="pixel"] .ninput, html[data-style="pixel"] .dpick,
html[data-style="pixel"] .fm-dest-input, html[data-style="pixel"] select {
  border:2px solid var(--line) !important; background:var(--panel2) !important; color:var(--text) !important;
}
html[data-style="pixel"] .toast { background:var(--accent); color:#fff; box-shadow:4px 4px 0 var(--pxshadow); }
/* 风格选择卡: 选中 = 黄底 + 硬阴影, 勾选角标变方块 */
html[data-style="pixel"] .stylepick button { border:2px solid var(--line); background:var(--panel2); }
html[data-style="pixel"] .stylepick button.on { background:var(--pxhi); color:var(--pxink); border-color:var(--pxink); box-shadow:3px 3px 0 var(--pxshadow); }
html[data-style="pixel"] .stylepick button.on::after { background:var(--pxink); color:var(--pxhi); }
html[data-style="pixel"] .stylepick .sw i { border:1px solid var(--line); }
</style><script>
/* 版本自检: 服务端升级后, 若当前页面仍是旧版本就自动重载 (看片时不打断, 最多 2 次防死循环) */
(function () {
  var MY = "__APP_VER__";
  function chk() {
    if (document.querySelector('.player.open')) return;
    var k = 'tsf_ver_chk', o = {};
    try { o = JSON.parse(sessionStorage.getItem(k) || '{}') || {}; } catch (e) { o = {}; }
    if (!o.t || Date.now() - o.t > 600000) o = { t: Date.now(), n: 0 };
    if ((o.n || 0) >= 2) return;
    fetch('/api/ver?t=' + Date.now(), { cache: 'no-store', credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.v && j.v !== MY) {
          o.n = (o.n || 0) + 1;
          try { sessionStorage.setItem(k, JSON.stringify(o)); } catch (e) {}
          location.reload();
        }
      }).catch(function () {});
  }
  document.addEventListener('visibilitychange', function () { if (!document.hidden) setTimeout(chk, 300); });
  window.addEventListener('load', function () { setTimeout(chk, 1200); });
})();
</script></head><body>
<!-- 内联 SVG 图标: 单文件自包含, 不引外链/字体; 线宽与颜色跟 currentColor 走,
     4 套界面风格 + 深浅色自动适配 (emoji 会随系统渲染成彩色卡通, 跟 UI 不搭) -->
<svg id="isprite" aria-hidden="true" focusable="false" style="position:absolute;width:0;height:0;overflow:hidden"><defs>
<symbol id="i-car" viewBox="0 0 24 24"><path d="M4.2 16.2h1.7m5.4 0h5.4m3.4 0h1.7"/><path d="M4.2 16.2v-2.6l4-1.7 2.6-2.9h4.4l2.6 2.9 4 1.7v2.6"/><circle cx="7.6" cy="16.3" r="1.7"/><circle cx="16.4" cy="16.3" r="1.7"/></symbol>
<symbol id="i-usb" viewBox="0 0 24 24"><rect x="3.4" y="7.4" width="17.2" height="9.2" rx="2"/><circle cx="16.4" cy="12" r="1.35"/><path d="M6.8 10.4h4.8"/></symbol>
<symbol id="i-theme" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.6"/><path d="M12 3.4a8.6 8.6 0 0 1 0 17.2z" fill="currentColor" stroke="none"/></symbol>
<symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.6v2.3M12 19.1v2.3M2.6 12h2.3M19.1 12h2.3M5.4 5.4l1.6 1.6M17 17l1.6 1.6M18.6 5.4 17 7M7 17l-1.6 1.6"/></symbol>
<symbol id="i-moon" viewBox="0 0 24 24"><path d="M20.4 13.7A8.4 8.4 0 1 1 10.3 3.6a6.7 6.7 0 0 0 10.1 10.1z"/></symbol>
<symbol id="i-gear" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3.1"/><path d="M19.1 14.9a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1.08-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 8.9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></symbol>
<symbol id="i-folder" viewBox="0 0 24 24"><path d="M21 18.5V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.7-.9l-.8-1.2A2 2 0 0 0 6.9 3H5a2 2 0 0 0-2 2v13.5a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2z"/></symbol>
<symbol id="i-volume" viewBox="0 0 24 24"><path d="M11.2 5.2 6.6 8.9H4.2a1 1 0 0 0-1 1v4.2a1 1 0 0 0 1 1h2.4l4.6 3.7z"/><path d="M15.2 9a4.2 4.2 0 0 1 0 6"/><path d="M17.8 6.4a7.8 7.8 0 0 1 0 11.2"/></symbol>
<symbol id="i-brush" viewBox="0 0 24 24"><path d="M14.4 4.6 19.4 9.6 9.2 19.8H4.2v-5z"/><path d="M12.4 6.6 17.4 11.6"/></symbol>
<symbol id="i-bell" viewBox="0 0 24 24"><path d="M18.2 8.8a6.2 6.2 0 1 0-12.4 0c0 4.9-2 6.4-2 6.4h16.4s-2-1.5-2-6.4"/><path d="M13.8 18.8a2.1 2.1 0 0 1-3.6 0"/></symbol>
<symbol id="i-key" viewBox="0 0 24 24"><circle cx="7.8" cy="15.8" r="3.6"/><path d="M10.4 13.2 20 3.6"/><path d="M17.2 6.4 19.6 8.8"/><path d="M14.6 9 17 11.4"/></symbol>
<symbol id="i-globe" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.6"/><path d="M3.4 12h17.2"/><path d="M12 3.4c2.5 2.6 3.6 5.5 3.6 8.6S14.5 18 12 20.6C9.5 18 8.4 15.1 8.4 12S9.5 6 12 3.4z"/></symbol>
<symbol id="i-image" viewBox="0 0 24 24"><rect x="3.4" y="4.4" width="17.2" height="15.2" rx="2"/><circle cx="8.6" cy="9.4" r="1.5"/><path d="m4.2 17.4 4.9-4.6a2 2 0 0 1 2.7 0l3.1 2.9 2-1.9a2 2 0 0 1 2.7 0l2.2 2.1"/></symbol>
<symbol id="i-refresh" viewBox="0 0 24 24"><path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20.2 4.2v5h-5"/></symbol>
<symbol id="i-archive" viewBox="0 0 24 24"><rect x="3.4" y="4.2" width="17.2" height="4.2" rx="1"/><path d="M5.2 8.4v9.2a2 2 0 0 0 2 2h9.6a2 2 0 0 0 2-2V8.4"/><path d="M10.2 12.4h3.6"/></symbol>
<symbol id="i-trash" viewBox="0 0 24 24"><path d="M4.4 7h15.2"/><path d="M9.6 7V5.3A1.3 1.3 0 0 1 10.9 4h2.2a1.3 1.3 0 0 1 1.3 1.3V7"/><path d="M6.4 7v11.7A1.6 1.6 0 0 0 8 20.3h8a1.6 1.6 0 0 0 1.6-1.6V7"/><path d="M10.4 10.8v6M13.6 10.8v6"/></symbol>
<symbol id="i-move" viewBox="0 0 24 24"><path d="M3.8 12h12.4"/><path d="m12.4 8 4.2 4-4.2 4"/><path d="M20.4 4.6v14.8"/></symbol>
<symbol id="i-copy" viewBox="0 0 24 24"><rect x="8.8" y="8.8" width="11.4" height="11.4" rx="2"/><path d="M15.2 5.6A1.6 1.6 0 0 0 13.6 4H5.6A1.6 1.6 0 0 0 4 5.6v8a1.6 1.6 0 0 0 1.6 1.6"/></symbol>
<symbol id="i-pen" viewBox="0 0 24 24"><path d="m4 20 4.6-1.1L19 8.5a2.1 2.1 0 0 0-3-3L5.6 16z"/><path d="m14.5 5.5 4 4"/></symbol>
<symbol id="i-eye" viewBox="0 0 24 24"><path d="M2.6 12S6.1 5.6 12 5.6 21.4 12 21.4 12 17.9 18.4 12 18.4 2.6 12 2.6 12z"/><circle cx="12" cy="12" r="2.9"/></symbol>
<symbol id="i-eye-off" viewBox="0 0 24 24"><path d="M4 4.2 20 20"/><path d="M9.7 5.9A9.4 9.4 0 0 1 12 5.6c5.9 0 9.4 6.4 9.4 6.4a17 17 0 0 1-2.5 3.4"/><path d="M6.4 7.3A16.6 16.6 0 0 0 2.6 12S6.1 18.4 12 18.4c1.3 0 2.5-.28 3.6-.76"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></symbol>
<symbol id="i-download" viewBox="0 0 24 24"><path d="M12 3.8v11.4"/><path d="m7.4 10.8 4.6 4.6 4.6-4.6"/><path d="M4.4 20h15.2"/></symbol>
<symbol id="i-link" viewBox="0 0 24 24"><path d="M9.6 14.4a4.2 4.2 0 0 0 6 0l2.6-2.6a4.2 4.2 0 0 0-6-6l-1.5 1.5"/><path d="M14.4 9.6a4.2 4.2 0 0 0-6 0L5.8 12.2a4.2 4.2 0 0 0 6 6l1.5-1.5"/></symbol>
<symbol id="i-brand" viewBox="0 0 24 24"><path d="M12 3.6l2.35 4.05 4.55.7-3.3 3.2.8 4.55L12 13.95 7.6 16.1l.8-4.55-3.3-3.2 4.55-.7z"/></symbol>
</defs></svg>
<header><h1><img class="blogo" id="blogo" src="/api/brand/logo" alt=""><span id="bname">TSL哨兵云盘</span></h1><span class="sub" id="stat"></span>
<span id="live" title="车机在线只读同步状态" style="display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:4px 10px;white-space:nowrap"><span id="livedot" style="width:7px;height:7px;border-radius:50%;background:#5f6b76"></span><span id="livetxt">同步状态</span></span>
<nav class="tabs" id="tabs"></nav><button id="theme" title="主题: 自动/浅色/深色" onclick="cycleTheme()"><svg class="ic"><use href="#i-theme"/></svg></button><button id="gear" title="设置"><svg class="ic"><use href="#i-gear"/></svg></button></header>
<nav class="storwrap" id="storwrap" style="display:none">
  <div class="storcard" id="storcard">
<div class="storrow"><span class="storlab">虚拟U盘</span><span class="storval" id="storvusb"></span></div>
<div class="storbar"><i id="storvusbbar"></i></div>
<div class="storextra" id="storextra">
<div class="storrow"><span class="storlab">归档区</span><span class="storval" id="storarc"></span></div>
<div class="storbar"><i id="storarcbar"></i></div>
<div class="storrow"><span class="storlab">总占用</span><span class="storval" id="stortot"></span></div>
<div class="storbar"><i id="stortotbar"></i></div>
<div class="storsys"><span class="storlab">系统状态</span><div class="sysgrid" id="storsys"></div></div>
</div>
<button class="stortog" id="stortog" onclick="toggleStor()" title="展开归档区、总占用与系统状态" aria-expanded="false" aria-controls="storextra"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9.5l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
  </div>
</nav>
<nav class="filters" id="filters"></nav>
<nav class="filters" id="dfilters"></nav>
<input type="date" id="dpick" class="dpick" onchange="if(this.value) setDate(this.value)">
<div class="grid-wrap" id="grid"></div>
<div class="empty" id="empty" style="display:none"><div class="big">📹</div>
<div>暂无归档视频<br><small style="font-size:12px">车机录制后, 归档同步任务会自动把视频收进来 (镜像需空闲10分钟)</small></div></div>

<div class="player" id="player">
  <div class="ptop">
    <button class="pback" onclick="closePlayer()">‹ 返回</button>
    <span class="ptitle" id="ptitle"></span>
    <button class="pdl" onclick="openExport()" title="导出"><svg class="ic"><use href="#i-download"/></svg></button>
  </div>
  <div class="pscroll">
    <div class="tpanel" id="tpanel">
        <div class="tp-top">
          <span class="tp-l"><span class="tp-date" id="tp-date">—</span><span class="tp-loc" id="tp-loc"></span><span class="tp-tag" id="tp-tag"></span></span>
          <span class="tp-tr"><span class="tp-sig" id="tp-bl" title="左转向灯"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="0.9" y="0.9" width="22.2" height="22.2" rx="6.2" fill="currentColor"/><path d="M17 12H8.2M12.2 7.3 7.5 12l4.7 4.7" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="tp-sig" id="tp-br" title="右转向灯"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="0.9" y="0.9" width="22.2" height="22.2" rx="6.2" fill="currentColor"/><path d="M7 12h8.8M11.8 7.3 16.5 12l-4.7 4.7" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="tp-gear" id="tp-gear">D</span></span>
        </div>
        <div class="tp-mid">
          <span class="tp-spd" id="tp-spd">0</span><span class="tp-unit">km/h</span>
          <span class="tp-badges">
            <span class="tp-badge brk" id="tp-brk" title="刹车 (数据源只有踩下/未踩, 无踏板开度)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="12" cy="12" r="7.6"/><circle cx="12" cy="12" r="2.5"/><path d="M17.4 6.6l2.7-2.7"/></svg><b>刹车</b></span>
            <span class="tp-badge thr" id="tp-thr" title="油门"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><path d="M9.4 3.6h5.2a1.7 1.7 0 0 1 1.68 1.93l-1.35 12.3a1.8 1.8 0 0 1-1.79 1.6h-2.28a1.8 1.8 0 0 1-1.79-1.6L7.72 5.53A1.7 1.7 0 0 1 9.4 3.6z"/><path d="M8.6 15.1h6.8"/></svg><b id="tp-thr-n">0%</b></span>
            <span class="tp-c st" id="tp-st" title="方向盘角度"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.6"/><path d="M3.2 10.5h6M14.8 10.5h6M12 14.6V21"/></svg></span>
          </span>
        </div>
        <button class="tp-fold" id="tp-fold" onclick="toggleTelRows()">收起详细数据 ⌃</button>
        <div class="tp-rows" id="tp-rows"></div>
    </div>
    <div class="vwrap">
      <div class="startmask" id="startmask">▶ 轻触开始同步播放</div>
      <div class="vgrid" id="vgrid"></div>
    </div>
    <div class="cambar" id="cambar"></div>
    <div class="infocard" id="infocard">
      <div class="ic-top"><span class="ic-time" id="ic-time">—</span><span class="ic-badge" id="ic-cat">—</span></div>
      <div class="ic-mid"><span class="ic-big" id="ic-big">—</span><span class="ic-sub" id="ic-sub"></span></div>
      <div class="clipbar" id="clipbar"></div>
      <button class="ic-fold" id="ic-fold" onclick="toggleDetail()">收起详细数据 ⌃</button>
      <div class="ic-rows" id="ic-rows"></div>
    </div>
  </div>
  <div class="pbar">
    <button class="pp" id="ppbtn" onclick="togglePlay()">⏸</button>
    <input type="range" id="seek" min="0" max="1000" value="0">
    <span class="t" id="ptime">00:00</span>
    <button class="spd" id="spdbtn" onclick="cycleSpeed()">1x</button>
    <div class="qsel" id="qsel"></div>
    <div class="qhint" id="qhint"></div>
  </div>
</div>

<div class="expp" id="expp">
  <div class="expt">选择要导出的画面<button class="x" onclick="closeExport()">✕</button></div>
  <div id="expchks"></div>
  <label class="expitem" id="expwm-row" style="border-top:1px solid var(--line2);margin-top:6px;align-items:flex-start">
    <input type="checkbox" id="expwm" style="margin-top:2px">
    <span style="line-height:1.45">叠加行车信息水印<small style="display:block;color:#7d8894;font-size:11px;margin-top:2px">半透明单行: 时间/位置/车速/挡位/油门/刹车, 基本不挡画面</small></span>
  </label>
  <div class="expitem" id="expfont-row" style="border-top:1px solid var(--line2);margin-top:6px;flex-direction:column;align-items:stretch;gap:7px">
    <span id="expfont-txt" style="font-size:12px;line-height:1.5;color:#7d8894">水印字体: 检查中…</span>
    <div id="expfont-btns" style="display:none;gap:8px">
      <button class="mini" id="expfont-btn" onclick="installFont()">安装字体</button>
      <button class="mini" id="expfont-up" onclick="document.getElementById('fontfile').click()">上传字体</button>
    </div>
    <input type="file" id="fontfile" accept=".ttf,.otf,.ttc" style="display:none" onchange="uploadFont(this)">
  </div>
  <div class="expitem" id="expq-row" style="border-top:1px solid var(--line2);margin-top:6px">
    <span style="flex:0 0 auto;color:#c6cdd4;cursor:default">下载清晰度</span>
    <div class="qsel" id="expq" style="flex:1;display:flex;justify-content:flex-end"></div>
  </div>
  <div class="expr">
    <button class="mini" onclick="expChk(true)">全选</button>
    <button class="mini" onclick="expChk(false)">清空</button>
    <button class="mini" onclick="doExportZip()">打包zip</button>
    <button class="mini" onclick="doPushFeishu()">推送飞书</button>
    <button class="mini primary" onclick="doExport()">合成视频</button>
  </div>
  <div class="hint" style="margin-top:8px;margin-bottom:0">单选取原文件直接下载(加水印时走本机合成)；多选合成一个多画面视频。下载/打包按所选清晰度导出(首次需等转码)。「推送飞书」按所选画面+水印合成后发到你的飞书私聊 (需已配置推送, 首次合成约1-3分钟)。</div>
</div>

<div class="mask" id="mask" onclick="closePanel()"></div>

<div class="livep" id="livep">
  <div class="lvtop">
    <span class="lvtitle">📡 准实时预览 <small style="color:#7d8894;font-weight:400">延时约 1~2 分钟</small></span>
    <span class="lvstatus" id="lv-status"></span>
  </div>
  <div class="lvbody">
    <div class="lvmeta" id="lv-name">—</div>
    <video id="lv-video" controls playsinline muted></video>
    <div class="lvgrid" id="lv-grid"></div>
    <div class="lvrow" id="lv-cams"></div>
    <div class="lvrow">
      <span style="font-size:13px;color:var(--muted)">画质</span>
      <select id="lv-q" onchange="setLiveQ(this.value)" title="与回放相同的几档画质; 非原画由设备后台转码, 首次先用已有档位立即开播, 转好后下次生效">
        <option value="orig">原画</option>
        <option value="720p">720p</option>
        <option value="480p">480p</option>
        <option value="360p">360p</option>
      </select>
    </div>
    <div class="lvrow">
      <span style="font-size:13px;color:var(--muted)">刷新检查</span>
      <select id="lv-iv" onchange="liveRestart()">
        <option value="15">15 秒</option>
        <option value="30">30 秒</option>
        <option value="60">1 分钟</option>
        <option value="0">仅手动</option>
      </select>
      <button class="lvbtn" onclick="liveTick()">检查更新</button>
    </div>
    <div class="hint">「全览」同时播放全部摄像头, 数据量较大 (4 路每分钟约 100MB), 建议流量充足时使用; 点任一格可切到单路。画质可选 原画 / 720p / 480p / 360p: 非原画由设备后台转码, 首次先用已有档位立即开播, 转好后下次打开即生效 (全览建议 480p 及以下)。原理: 车机循环录制 1 分钟一段; 后台的只读同步 (不打断车机) 把刚写完的片段持续收进归档, 这里自动发现并播放最新片段, 即约 1 分钟延时的"直播"。刚停车/刚触发录像的片段要等写完才会出现。</div>
  </div>
</div>
<div class="panel" id="panel">
  <h2><svg class="ic"><use href="#i-gear"/></svg>个性化 <button class="x" onclick="closePanel()">✕</button></h2>
  <div class="stabs">
    <button class="stab" id="st-net" onclick="stab('net')"><svg class="ic"><use href="#i-globe"/></svg>网络设置</button>
    <button class="stab active" id="st-files" onclick="stab('files')"><svg class="ic"><use href="#i-folder"/></svg>文件</button>
    <button class="stab" id="st-audio" onclick="stab('audio')"><svg class="ic"><use href="#i-volume"/></svg>锁车语音</button>
    <button class="stab" id="st-wraps" onclick="stab('wraps')"><svg class="ic"><use href="#i-brush"/></svg>涂装</button>
    <button class="stab" id="st-notify" onclick="stab('notify')"><svg class="ic"><use href="#i-bell"/></svg>推送</button>
    <button class="stab" id="st-auth" onclick="stab('auth')"><svg class="ic"><use href="#i-key"/></svg>账号</button>
    <button class="stab" id="st-lang" onclick="stab('lang')"><svg class="ic"><use href="#i-globe"/></svg>语言</button>
    <button class="stab" id="st-skin" onclick="stab('skin')"><svg class="ic"><use href="#i-image"/></svg>网页背景</button>
    <button class="stab" id="st-fan" onclick="stab('fan')"><svg class="ic"><use href="#i-gear"/></svg>风扇设置</button>
    <button class="stab" id="st-brand" onclick="stab('brand')"><svg class="ic"><use href="#i-brand"/></svg>品牌</button>
    <button class="stab" id="st-update" onclick="stab('update')"><svg class="ic"><use href="#i-refresh"/></svg>更新</button>
  </div>
  <div id="tab-net" style="display:none">
    <div class="hint" id="net-roll" style="display:none;color:#e8443f"></div>
    <div class="brandrow" id="net-roll-row" style="display:none"><button class="primary" onclick="netConfirm()">确认连接</button></div>
    <b style="font-size:13px">有线网络</b>
    <div class="hint" id="net-wired-live">--</div>
    <div class="brandrow">
      <select id="net-wmode" class="storage-select" onchange="netWMode()">
        <option value="dhcp">自动获取 (DHCP)</option>
        <option value="static">静态地址</option>
      </select>
    </div>
    <div id="net-static" style="display:none">
      <div class="brandrow"><input class="ninput" id="net-ip" placeholder="IP 地址" autocomplete="off"></div>
      <div class="brandrow"><input class="ninput" id="net-prefix" placeholder="掩码位数" value="24" autocomplete="off"></div>
      <div class="brandrow"><input class="ninput" id="net-gw" placeholder="网关" autocomplete="off"></div>
      <div class="brandrow"><input class="ninput" id="net-dns" placeholder="DNS (逗号分隔)" autocomplete="off"></div>
    </div>
    <div class="brandrow"><button class="primary" onclick="netApplyWired()">应用有线设置</button></div>
    <b style="font-size:13px;margin-top:10px;display:block">无线网络</b>
    <div class="hint" id="net-wifi-live">--</div>
    <div class="brandrow">
      <button class="storage-btn" onclick="netScan()">扫描无线</button>
      <button class="storage-btn" onclick="netForget()">忘记网络</button>
    </div>
    <div id="net-aps" style="display:flex;flex-wrap:wrap;gap:6px;margin:6px 0"></div>
    <div class="brandrow"><input class="ninput" id="net-ssid" placeholder="SSID" autocomplete="off"></div>
    <div class="brandrow"><input class="ninput" id="net-psk" type="password" placeholder="无线密码 (留空为开放网络)" autocomplete="new-password"></div>
    <div class="brandrow"><button class="primary" onclick="netApplyWifi()">连接无线</button></div>
    <b style="font-size:13px;margin-top:10px;display:block">个人热点</b>
    <div class="hint" id="net-ap-live">--</div>
    <div class="brandrow">
      <select id="net-ap-enable" class="storage-select">
        <option value="0">关闭</option>
        <option value="auto">自动</option>
        <option value="1">开启</option>
      </select>
    </div>
    <div class="brandrow"><input class="ninput" id="net-ap-ssid" placeholder="热点名称" autocomplete="off"></div>
    <div class="brandrow"><input class="ninput" id="net-ap-psk" placeholder="热点密码 (8-63位)" autocomplete="new-password"></div>
    <div class="brandrow">
      <span class="hint" style="margin:0;align-self:center">频段</span>
      <select id="net-ap-band" class="storage-select">
        <option value="auto">自动</option>
        <option value="2g">2.4G</option>
        <option value="5g">5G</option>
      </select>
      <span class="hint" style="margin:0;align-self:center">信道</span>
      <select id="net-ap-chmode" class="storage-select" onchange="netApChMode()">
        <option value="auto">自动</option>
        <option value="manual">手动</option>
      </select>
      <input class="ninput" id="net-ap-ch" type="number" min="1" max="165" style="width:90px;display:none" placeholder="信道">
    </div>
    <div class="hint">频段/信道: 自动跟随已连 WiFi; 当前网卡仅支持 2.4G 热点 (5G 不允许发射)。</div>
    <div class="hint">连着 WiFi 时热点跟随同信道; 未连接默认 2.4G ch6。客户端分 192.168.50.x 并共享有线上网。</div>
    <div class="brandrow"><button class="primary" onclick="netApplyAp()">应用热点设置</button></div>
    <b style="font-size:13px;margin-top:10px;display:block">蓝牙</b>
    <div class="hint" id="net-bt-live">--</div>
    <div class="brandrow">
      <select id="net-bt-power" class="storage-select">
        <option value="0">关闭</option>
        <option value="1">开启</option>
      </select>
      <select id="net-bt-disc" class="storage-select">
        <option value="0">不可被发现</option>
        <option value="1">可被发现</option>
      </select>
    </div>
    <div class="brandrow"><input class="ninput" id="net-bt-name" placeholder="蓝牙名称" autocomplete="off"></div>
    <div class="brandrow">
      <button class="primary" onclick="netApplyBt()">应用蓝牙设置</button>
      <button class="storage-btn" onclick="netBtScan()">扫描蓝牙</button>
    </div>
    <div id="net-bt-devs" style="display:flex;flex-wrap:wrap;gap:6px;margin:6px 0"></div>
    <div class="hint" id="net-err" style="display:none;color:#e8443f"></div>
  </div>
  <div id="tab-brand" style="display:none">
    <div class="hint">标题栏左侧的图标与名称 · 改完立即生效, 访客刷新页面后看到新的; 名称留空即用默认「TSL哨兵云盘」</div>
    <div class="brandbox">
      <img class="blogo" id="brand-prev" src="/api/brand/logo" alt="">
      <div class="brandmeta"><b id="brand-prevname">TSL哨兵云盘</b><span>当前效果</span></div>
    </div>
    <div class="brandrow">
      <input class="ninput" id="brand-name" maxlength="24" placeholder="TSL哨兵云盘" autocomplete="off" autocapitalize="none" onkeydown="if(event.key==='Enter')saveBrandName()">
      <button class="primary" onclick="saveBrandName()">保存</button>
    </div>
    <label class="upbtn">＋ 上传图标 (png/jpg/webp, ≤3MB)<input type="file" id="brand-file" accept=".png,.jpg,.jpeg,.webp" hidden></label>
    <div style="margin-top:4px"><button class="brandreset" onclick="resetBrand()">恢复默认图标与名称</button></div>
  </div>
  <div id="tab-skin" style="display:none">
    <div class="hint">界面风格 · 只换配色、圆角与阴影, 不动功能; 选完即时生效并记住</div>
    <div class="stylepick" id="style-pick">
      <button data-style="default" onclick="setStyle('default')"><span class="sw"><i style="background:#0e1216"></i><i style="background:#e8443f"></i></span>默认</button>
      <button data-style="apple" onclick="setStyle('apple')"><span class="sw"><i style="background:#ffffff"></i><i style="background:#0071e3"></i></span>Apple</button>
      <button data-style="claude" onclick="setStyle('claude')"><span class="sw"><i style="background:#faf9f5"></i><i style="background:#c96442"></i></span>Claude</button>
      <button data-style="pixel" onclick="setStyle('pixel')"><span class="sw"><i style="background:#1a1c2c"></i><i style="background:#ff004d"></i></span>像素</button>
    </div>
    <div class="hint">上传 CSS 皮肤文件或背景图 (jpg/png/webp)。CSS 中引用图片请用 /skin-media/文件名。</div>
    <div class="hint"><code>body{background:url(/skin-media/bg.jpg) center/cover}</code></div>
    <label class="upbtn">＋ 上传皮肤文件 (css/jpg/png/webp)<input type="file" id="skin-file" accept=".css,.jpg,.jpeg,.png,.webp" hidden></label>
    <div id="skin-list"></div>
  </div>
  <div id="tab-fan" style="display:none">
    <div class="hint">自动模式按温度调速: 45°C 以下停转, 75°C 全速; 手动模式立即生效</div>
    <div class="brandrow" style="margin-top:8px">
      <select id="fan-mode" class="storage-select" onchange="fanModeChange()">
        <option value="auto">自动温控</option>
        <option value="manual">手动定速</option>
      </select>
    </div>
    <div class="storage-slider-row" id="fan-manual-row">
      <span>风扇转速</span>
      <input id="fan-duty" class="storage-range" type="range" min="0" max="100" value="50" oninput="document.getElementById('fan-duty-text').textContent=this.value+'%'">
      <span id="fan-duty-text" class="storage-percent">50%</span>
    </div>
    <div class="hint" id="fan-live">当前温度 -- · 当前占空比 --</div>
    <div class="brandrow"><button class="primary" onclick="fanSave()">保存风扇设置</button></div>
    <div class="hint" id="fan-err" style="display:none;color:#e8443f"></div>
  </div>
  <div id="tab-audio" style="display:none">
    <div class="hint">上传的音频 (wav/mp3, &lt;1MB) 会直接写入车机U盘根目录；文件名为 LockChime.wav 的即锁车音 (特斯拉只认根目录这个文件名)。文件在归档同步时写入车机U盘。</div>
    <label class="upbtn">＋ 上传音频 (wav/mp3, &lt;1MB)<input type="file" id="audio-file" accept=".wav,.mp3" hidden></label>
    <div class="hint" style="color:#4cc38a">⏳ 待写入车机U盘:</div>
    <div id="audio-list"></div>
    <div class="hint" style="color:#4cc38a">✅ 已写入:</div>
    <div id="audio-done"></div>
  </div>
  <div id="tab-wraps" style="display:none">
    <div class="hint">车机涂装/牌照图片: 上传 png/jpg/webp, 直接写入车机U盘根目录 Wraps/ (车机端设置里选)。连接时会临时断开车机读取几秒, 用完点「恢复车机导出」; 5 分钟无操作也会自动恢复。</div>
    <div id="wraps-status" style="margin-bottom:10px"></div>
    <label class="upbtn" id="wraps-upbtn">＋ 上传图片到 Wraps/ (png/jpg/webp, ≤100MB)<input type="file" id="wraps-file" accept=".png,.jpg,.jpeg,.webp" hidden multiple></label>
    <div id="wraps-grid" style="display:flex;flex-wrap:wrap;gap:10px;margin-top:12px"></div>
  </div>
  <div id="tab-files">
    <div style="display:flex;gap:8px;margin-bottom:10px">
      <button id="area-usb" class="stab active" style="flex:1" onclick="switchArea('usb')"><svg class="ic"><use href="#i-usb"/></svg>车机U盘</button>
      <button id="area-archive" class="stab" style="flex:1" onclick="switchArea('archive')"><svg class="ic"><use href="#i-archive"/></svg>归档区</button>
    </div>
    <div id="usb-status" style="display:none;margin-bottom:10px"></div>
    <div id="usb-hint" class="hint">浏览和管理车机U盘 (特斯拉写入的镜像)。连接后会临时断开车机读取几秒，5 分钟无操作自动恢复。</div>
    <div id="storage-panel" class="storage-card">
      <div class="storage-head">
        <b style="font-size:13px">设备与存储</b>
        <button class="storage-btn" onclick="refreshStorage()">刷新</button>
      </div>
      <div id="storage-status" class="hint">正在读取...</div>
      <div id="storage-disks" style="margin-top:8px"></div>
      <div class="storage-alloc">
        <b style="font-size:12.5px">新建存储方案 <span class="storage-danger">(会清空所选硬盘)</span></b>
        <div class="storage-form-row">
          <span>选择硬盘</span>
          <select id="alloc-device" class="storage-select" onchange="storageAllocCalc()"></select>
        </div>
        <div class="storage-slider-row">
          <span>虚拟U盘占比</span>
          <input id="alloc-percent" class="storage-range" type="range" min="10" max="90" value="50" oninput="storageAllocCalc()">
          <span id="alloc-percent-text" class="storage-percent">50%</span>
        </div>
        <div id="alloc-calc" class="hint storage-calc"></div>
        <button class="storage-init" onclick="storageInit()">输入序列号并格式化应用</button>
      </div>
    </div>
    <div id="arch-hint" class="hint" style="display:none">归档区（外接 U 盘）：查看器视频副本、皮肤和文件中转；文件保存在外接盘，不占用系统盘。</div>
    <div id="purge-box" class="fm-purge">
      <button onclick="purgeTeslaCam()"><svg class="ic"><use href="#i-trash"/></svg>清空 TeslaCam 全部录像</button>
      <span class="hint">仅删除 TeslaCam/ 内所有视频与事件文件夹，保留目录结构；Boombox、Wraps 等其他根目录不受影响。需先连接 U 盘。</span>
    </div>
    <div id="dir-nav" style="display:none">
      <div style="display:flex;gap:8px;margin-bottom:10px">
        <input id="dest-dir" placeholder="/" style="flex:1;background:#161c22;border:1px solid #3a4652;border-radius:8px;color:#e8eaed;padding:8px 10px;font-size:12px;outline:none">
        <button onclick="goDir(document.getElementById('dest-dir').value)" style="background:#e8443f;border:none;color:#fff;border-radius:8px;padding:0 14px;font-size:12px;cursor:pointer">跳转</button>
      </div>
      <div id="crumb" style="font-size:12px;color:#5ea9ff;margin-bottom:8px;line-height:1.8"></div>
      <label class="upbtn" id="upbtn">＋ 上传文件到当前目录 (任意类型, ≤100MB)<input type="file" id="anyfile-file" hidden></label>
      <div id="fm-bar" class="fm-bar">
        <div class="row" style="justify-content:space-between;margin-bottom:8px">
          <label class="row" style="cursor:pointer;font-size:12.5px;gap:6px">
            <input type="checkbox" id="fm-all" style="width:17px;height:17px;accent-color:var(--accent);cursor:pointer" onchange="fmAll(this.checked)"> 全选
          </label>
          <span class="fm-count" id="fm-count">已选 0 项</span>
        </div>
        <div class="row">
          <button class="fm-danger" onclick="fmOp('delete')"><svg class="ic"><use href="#i-trash"/></svg>删除</button>
          <button onclick="fmOp('move')"><svg class="ic"><use href="#i-move"/></svg>移动</button>
          <button onclick="fmOp('copy')"><svg class="ic"><use href="#i-copy"/></svg>复制</button>
          <button onclick="fmOp('rename')"><svg class="ic"><use href="#i-pen"/></svg>重命名</button>
        </div>
        <div class="row" id="fm-dest" style="display:none;margin-top:8px">
          <input class="fm-dest-input" id="fm-dest-input" placeholder="目标目录">
          <button class="fm-go" onclick="fmDestGo()">执行</button>
          <button onclick="fmDestCancel()">取消</button>
        </div>
      </div>
      <div id="file-list"></div>
    </div>
  </div>
  <div id="tab-notify" style="display:none">
    <div class="hint">哨兵触发时把时间/位置/触发原因和触发画面推到飞书。默认走自建应用私聊(只有你本人可见)；也可切到群机器人 webhook(群里都能看到)。视频推送只支持私聊。</div>
    <label class="nrow"><span>启用推送</span><input type="checkbox" id="nt-en"></label>
    <label class="nrow"><span>也推手动保存</span><input type="checkbox" id="nt-saved"></label>
    <select class="ninput" id="nt-mode">
      <option value="dm">私聊推送 — 只有我本人能看到</option>
      <option value="group">群机器人 — 群里所有人都能看到</option>
    </select>
    <div class="eyebar">
      <span class="lbl" id="nt-eyetip">敏感信息已隐藏（截图安全）</span>
      <button class="mini" id="nt-eye" onclick="ntToggleEye()"><svg class="ic"><use href="#i-eye"/></svg>显示</button>
    </div>
    <input class="ninput" id="nt-to" placeholder="接收人: 你的 open_id (ou_ 开头) 或飞书登录邮箱">
    <select class="ninput" id="nt-media" onchange="ntMediaUI()">
      <option value="thumb">推送内容：封面卡片（触发那帧图 + 信息，最快）</option>
      <option value="video">推送内容：触发摄像头视频（可回放）</option>
    </select>
    <div id="nt-vwrap" style="display:none">
      <select class="ninput" id="nt-quality">
        <option value="720p">视频清晰度：720p（约 5MB / 30 秒）</option>
        <option value="480p">视频清晰度：480p（约 3MB / 30 秒）</option>
        <option value="360p">视频清晰度：360p（约 1.8MB / 30 秒）</option>
      </select>
      <div class="nrow"><span>视频时长</span><input class="ninput num" id="nt-vdur" type="number" min="10" max="60"> <span class="hint2">秒（从触发前 5 秒开始截）</span></div>
    </div>
    <input class="ninput" id="nt-appid" placeholder="App ID — cli_ 开头">
    <input class="ninput" id="nt-secret" type="password" placeholder="App Secret (已保存则留空表示不修改)">
    <input class="ninput" id="nt-hook" placeholder="群机器人 webhook (仅群推送需要): https://open.feishu.cn/open-apis/bot/v2/hook/...">
    <input class="ninput" id="nt-url" placeholder="查看链接前缀 (可选): http://你的域名:端口">
    <div class="nrow"><span>延迟推送</span><input class="ninput num" id="nt-delay" type="number" min="5" max="600"> <span class="hint2">秒 (等片段写完再推)</span></div>
    <div class="updbtns">
      <button class="mini primary" onclick="ntSave()">保存设置</button>
      <button class="mini" onclick="ntTest()">发送测试</button>
    </div>
    <div class="hint" id="nt-msg"></div>
  </div>
  <div id="tab-auth" style="display:none">
    <div class="hint">改完本机会自动用新密码重新登录，手机/其它设备上的登录状态立即失效。</div>
    <input class="ninput" id="pw-old" type="password" placeholder="当前密码" autocomplete="current-password">
    <input class="ninput" id="pw-new" type="password" placeholder="新密码 (至少 6 位)" autocomplete="new-password">
    <input class="ninput" id="pw-new2" type="password" placeholder="再输一次新密码" autocomplete="new-password">
    <div class="updbtns"><button class="mini primary" onclick="pwSave()">修改密码</button></div>
    <div class="hint" id="pw-msg"></div>
    <div class="hint" style="margin-top:12px"><span>用户名</span>: <b id="pw-user">admin</b></div>
    <div class="hint">要改用户名请编辑设备上 /opt/tesla-sentry/auth.conf 的 user=</div>
    <div class="updbtns" style="margin-top:16px"><button class="mini logout" onclick="doLogout()">退出登录</button></div>
  </div>
  <div id="tab-update" style="display:none">
    <div class="updrow"><span class="updk">当前版本</span><b id="upd-cur">—</b></div>
    <div class="updrow"><span class="updk">最新版本</span><b id="upd-new">—</b><span class="updtag" id="upd-tag">未检查</span></div>
    <div class="updnotes" id="upd-notes"></div>
    <label class="updauto" title="检测到新版本时, 在没人看视频的空闲时刻自动升级 (只重启本服务, 约 5 秒)">
      <span>自动更新</span>
      <input type="checkbox" id="upd-auto" checked onchange="setAutoUpdate(this.checked)">
    </label>
    <div class="hint" id="upd-autohint">—</div>
    <div class="updbtns">
      <button class="mini" id="upd-check" onclick="otaCheck(true)">检查更新</button>
      <button class="mini primary" id="upd-go" onclick="otaApply()" disabled>立即升级</button>
    </div>
    <div class="hint" id="upd-msg"></div>
    <div class="updbtns"><button class="mini" id="upd-rb" onclick="otaRollback()" style="display:none">↩ 回滚到上一版本</button></div>
    <div class="hint">升级会从 GitHub 及多个镜像并发竞速拉取最新程序, 覆盖本机文件并自动重启服务 (约5秒); 配置、录像、登录信息不受影响。</div>
  </div>
  <div id="tab-lang" style="display:none">
    <div class="hint" style="margin-bottom:8px">选择语言</div>
    <div class="langgrid" id="lang-grid"></div>
    <div class="hint">界面语言，保存在本机浏览器</div>
  </div>
</div>
<div class="toast" id="toast"></div>

<div class="stitch" id="stitch">
  <div class="stbox">
    <div class="stt">正在合成多画面视频</div>
    <div class="stbar"><div class="stfill" id="stfill"></div></div>
    <div class="stpct" id="stpct">0%</div>
    <div class="sthint" id="sthint">设备正在拼接各路画面, 请勿关闭页面</div>
  </div>
</div>

<script>window.__I18N=__I18N__;window.__LANGS=__LANGS__;</script>
<script>
let data = {}, cur = null, syncTimer = null, currentCat = 'SentryClips', lastSig = '', reasonFilter = 'all', dateFilter = 'all';
let curClips = [], curClipIx = 0, TEL = null;

/* ---------- 多语言 ----------
   字典以中文原文为 key; 静态文案由 applyLang() 遍历 DOM 替换, 动态文案在生成时用 t() 包一层。
   切回中文时从节点上保存的原文还原, 不会叠加翻译。 */
const I18N = window.__I18N || {};
const LANGS = window.__LANGS || [['zh', '中文']];
let LANG = (localStorage.getItem('tsf_lang') || '').trim();
if (!LANGS.some(l => l[0] === LANG)) {
  LANG = 'zh';
}
function t(s) {
  if (!s || LANG === 'zh') return s;
  const m = I18N[LANG] || {};
  return m[s] || (I18N.en || {})[s] || s;
}
function langName(code) {
  const l = LANGS.find(x => x[0] === code);
  return l ? l[1] : code;
}
const ZH_TXT = '__zh', ZH_TV = '__tv', ZH_ATTR = '__zha';
function applyLang() {
  document.documentElement.lang = (LANG === 'zh') ? 'zh-CN' : LANG;
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
  const nodes = [];
  while (w.nextNode()) nodes.push(w.currentNode);
  for (const n of nodes) {
    const p = n.parentNode;
    if (!p) continue;
    const tag = p.nodeName;
    if (tag === 'SCRIPT' || tag === 'STYLE') continue;
    if (p.id === 'bname' || p.id === 'brand-prevname') continue;   // 品牌名由 applyBrand 单独管, 不参与翻译
    const cur = n.nodeValue;
    if (n[ZH_TXT] !== undefined && cur !== n[ZH_TV] && cur !== n[ZH_TXT]) n[ZH_TXT] = cur;
    if (n[ZH_TXT] === undefined) n[ZH_TXT] = cur;
    const raw = n[ZH_TXT], key = (raw || '').trim();
    if (!key) continue;
    const val = t(key);
    n.nodeValue = (val === key) ? raw : raw.replace(key, val);
    n[ZH_TV] = n.nodeValue;
  }
  document.querySelectorAll('[placeholder],[title]').forEach(el => {
    ['placeholder', 'title'].forEach(a => {
      if (!el.hasAttribute(a)) return;
      el[ZH_ATTR] = el[ZH_ATTR] || {};
      if (el[ZH_ATTR][a] === undefined) el[ZH_ATTR][a] = el.getAttribute(a);
      const raw = el[ZH_ATTR][a], key = (raw || '').trim();
      if (!key) return;
      const val = t(key);
      el.setAttribute(a, val === key ? raw : raw.replace(key, val));
    });
  });
  const g = document.getElementById('lang-grid');
  if (g) renderLangGrid();
  applyBrand();
}
function renderLangGrid() {
  const g = document.getElementById('lang-grid');
  if (!g) return;
  g.innerHTML = LANGS.map(([c, n]) =>
    '<button class="' + (c === LANG ? 'on' : '') + '" onclick="setLang(\'' + c + '\')">' +
    n + '<span class="code">' + c.toUpperCase() + '</span></button>').join('');
}
function setLang(code) {
  if (!LANGS.some(l => l[0] === code)) return;
  LANG = code;
  localStorage.setItem('tsf_lang', code);
  applyLang();
  const th = localStorage.getItem('tsf_theme') || 'auto';
  const b = document.getElementById('theme');
  if (b) b.title = t('主题') + ': ' + t(th === 'auto' ? '自动' : th === 'light' ? '浅色' : '深色');
  if (typeof data !== 'undefined' && data && document.getElementById('tabs')) { try { load(); } catch (e) {} }
}

/* ---------- 主题: 自动(跟系统) / 浅色 / 深色, 手动循环切换并记住 ---------- */
const THEME_ICONS = { auto: 'i-theme', light: 'i-sun', dark: 'i-moon' };
const THEME_NEXT = { auto: 'light', light: 'dark', dark: 'auto' };
function applyTheme(mode) {
  let eff = mode;
  if (mode === 'auto') {
    eff = window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  document.documentElement.dataset.theme = eff;
  const b = document.getElementById('theme');
  if (b) { b.innerHTML = '<svg class="ic"><use href="#' + (THEME_ICONS[mode] || 'i-theme') + '"/></svg>';
    b.title = t('主题') + ': ' + t(mode === 'auto' ? '自动' : mode === 'light' ? '浅色' : '深色'); }
}
function cycleTheme() {
  const cur = localStorage.getItem('tsf_theme') || 'auto';
  const nxt = THEME_NEXT[cur] || 'auto';
  localStorage.setItem('tsf_theme', nxt);
  applyTheme(nxt);
}
applyTheme(localStorage.getItem('tsf_theme') || 'auto');
/* ---------- 可选界面风格: 默认 / Apple / Claude / 像素 ----------
   只切换 html[data-style], 配色与圆角交给 CSS; 选择存本地并同步到服务端,
   换手机/浏览器也能保持一致。和深/浅色主题互不影响 */
const STYLE_KEY = 'tsf_style';
const STYLE_LIST = ['default', 'apple', 'claude', 'pixel'];
function applyStyle(s) {
  if (STYLE_LIST.indexOf(s) < 0) s = 'default';
  if (s === 'default') delete document.documentElement.dataset.style;
  else document.documentElement.dataset.style = s;
  const box = document.getElementById('style-pick');
  if (box) box.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.style === s));
}
function setStyle(s) {
  if (STYLE_LIST.indexOf(s) < 0) return;
  applyStyle(s);
  try { localStorage.setItem(STYLE_KEY, s); } catch (e) {}
  try {
    fetch('/api/ui/style', { method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ style: s }) }).catch(() => {});
  } catch (e) {}
}
applyStyle(localStorage.getItem(STYLE_KEY) || 'default');
/* 本地没选过时跟随服务端保存的风格 (在别的设备上设过) */
(function () {
  try { if (localStorage.getItem(STYLE_KEY)) return; } catch (e) { return; }
  fetch('/api/settings', { cache: 'no-store' }).then(r => r.json()).then(j => {
    if (j && j.ui_style) applyStyle(j.ui_style);
  }).catch(() => {});
})();
/* ---------- 存储卡展开/收起 ----------
   默认只显示「虚拟U盘」一行; 点卡片右下角小箭头才展开「归档区 / 总占用」 */
function toggleStor() {
  const c = document.getElementById('storcard'), b = document.getElementById('stortog');
  if (!c || !b) return;
  const open = c.classList.toggle('open');
  b.title = open ? '收起归档区、总占用与系统状态' : '展开归档区、总占用与系统状态';
  b.setAttribute('aria-expanded', open ? 'true' : 'false');
}
if (window.matchMedia) matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if ((localStorage.getItem('tsf_theme') || 'auto') === 'auto') applyTheme('auto');
});
/* ---------- 清晰度选择: 本地原片直解 / 远程低码率转码 ----------
   局域网首次打开默认原画, 浏览器直接解码, 不触发设备端转码;
   非局域网首次打开默认 360p, 由设备生成低码率缓存后传输。
   两种网络分别记住手动选择, VPN/域名访问不可靠时不强行改档, 仍可由用户切换。 */
const Q_LIST = [['orig', '原画'], ['720p', '720p'], ['480p', '480p'], ['360p', '360p']];
const isLanNet = /^(100\.96\.|192\.168\.|10\.|127\.)/.test(location.hostname) || location.hostname === 'localhost';
const Q_NET_MODE = isLanNet ? 'lan' : 'wan';
const Q_STORE_KEY = 'tsfq4-' + Q_NET_MODE;
let curQ = localStorage.getItem(Q_STORE_KEY) || (isLanNet ? 'orig' : '360p');
/* 已提前提交过后台转码的 (分类+画质+事件列表) 组合, 避免 10 秒轮询重复 POST */
let prekicked = new Set();
/* 苹果设备: 合成改走设备端 (Safari 的 MediaRecorder 只能出 webm, 微信不认) */
const IS_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
               (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
if (!Q_LIST.some(x => x[0] === curQ)) curQ = isLanNet ? 'orig' : '360p';
function qUrl(u) {
  if (curQ === 'orig') return u;
  let x = u + '?q=' + curQ;
  if (playbackSid) x += '&sid=' + encodeURIComponent(playbackSid);
  return x;
}
/* 播放器会话: 打开才完整转码, 退出/关页立即通知服务端停止。 */
let playbackSid = null, playbackTimer = null;
function playbackPaths() {
  return [...document.querySelectorAll('#vgrid video')].map(v => v._baseUrl || v.src.split('?')[0]);
}
function sendPlaybackBeat() {
  if (!playbackSid) return;
  try {
    fetch('/api/playback/beat', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({sid: playbackSid, q: curQ, paths: playbackPaths()}), keepalive: true}).catch(() => {});
  } catch (e) {}
}
function startPlaybackSession() {
  stopPlaybackSession();
  playbackSid = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
    : String(Date.now()) + Math.random().toString(16).slice(2);
  sendPlaybackBeat();
  playbackTimer = setInterval(sendPlaybackBeat, 5000);
}
function stopPlaybackSession() {
  if (playbackTimer) { clearInterval(playbackTimer); playbackTimer = null; }
  if (!playbackSid) return;
  const sid = playbackSid; playbackSid = null;
  const payload = JSON.stringify({sid});
  try {
    if (navigator.sendBeacon) {
      navigator.sendBeacon('/api/playback/leave', new Blob([payload], {type: 'application/json'}));
    } else {
      fetch('/api/playback/leave', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: payload, keepalive: true}).catch(() => {});
    }
  } catch (e) {}
}
window.addEventListener('pagehide', stopPlaybackSession);
function renderQSel() {
  const curLabel = (Q_LIST.find(x => x[0] === curQ) || Q_LIST[0])[1];
  document.getElementById('qsel').innerHTML =
    `<button class="qbtn ${curQ !== 'orig' ? 'on' : ''}" title="${curQ === 'orig' ? '原画由浏览器直接解码' : '非原画由盒子转码后传输'} · ${isLanNet ? '本地网络' : '远程网络'}" onclick="toggleQ(event)">${curLabel} ⌃</button>` +
    '<div class="qmenu">' + Q_LIST.map(([k, label]) =>
      `<button class="${k === curQ ? 'on' : ''}" onclick="setQuality('${k}')">${label}</button>`).join('') + '</div>';
}
function toggleQ(e) {
  if (e) e.stopPropagation();
  document.getElementById('qsel').classList.toggle('open');
}
function closeQ() {
  ['qsel', 'expq'].forEach(id => { const el = document.getElementById(id); if (el) el.classList.remove('open'); });
}
document.addEventListener('click', closeQ);
function setQuality(q) {
  closeQ();
  if (q === curQ) return;
  curQ = q; localStorage.setItem(Q_STORE_KEY, q);
  renderQSel();
  if (!cur) return;
  // 记住各路播放进度与播放状态, 换源后续播
  const v0el = document.querySelector('#vgrid video');
  const wasPlaying = v0el ? !v0el.paused : false;
  const times = [...document.querySelectorAll('#vgrid video')].map(v => v.currentTime || 0);
  const hint = document.getElementById('qhint');
  /* 延迟提示取消: 现在 /media 未命中画质缓存时先给原画 + 后台转码, 首帧不再干等
     十几秒, 只需说明「本次是原画、转好后下次生效」即可 */
  clearTimeout(setQuality._ht); clearTimeout(setQuality._show);
  hint.style.display = 'none';
  if (q !== 'orig') {
    hint.textContent = '正在后台生成 ' + q + ' 画质, 本次先用现有档位播放 (切段或下次打开即生效)';
    hint.style.display = 'block';
    setQuality._ht = setTimeout(() => { hint.style.display = 'none'; }, 6000);
  }
  { prekicked.clear(); prekickList(); }
  renderClip();
  const vids = [...document.querySelectorAll('#vgrid video')];
  vids.forEach((v, i) => {
    const seek = () => { try { if (times[i]) v.currentTime = times[i]; } catch (e) {} };
    if (v.readyState >= 1) seek();
    else v.addEventListener('loadedmetadata', seek, { once: true });
  });
  /* tryPlay 需要传 video 参数: 以前这里 tryPlay() 无参调用会抛 TypeError,
     表现为切清晰度后视频停在暂停态、还得再手动点一下播放 */
  if (wasPlaying) playAll();
  // 第一路能播就撤提示
  const v0 = vids[0];
  if (v0) v0.addEventListener('canplay', () => { hint.style.display = 'none'; }, { once: true });
}
const CATS_NAME = __CAT_NAMES__;
/* event.json 里的 reason → 中文名 (reason 是自由文本, 新值靠前缀匹配兜底) */
const REASON_LABEL = {
  sentry_aware_object_detection: '哨兵警觉',
  sentry_aware_door: '车门拉动',
  sentry_aware_handle: '车门拉动',
  sentry_aware_accel: '遭遇袭击',
  sentry_panic: '遭遇袭击',
  sentry_trigger: '哨兵模式触发',
  user_interaction_dashcam_saved: '手动保存',
  user_interaction_dashcam_menu: '行车记录仪菜单保存',
  user_interaction_dashcam_launcher_action_tapped: '点击行车记录仪图标',
  user_interaction_honk: '按喇叭保存'
};
function reasonLabel(r) {
  if (!r) return '';
  if (REASON_LABEL[r]) return t(REASON_LABEL[r]);
  for (const k in REASON_LABEL) if (r.indexOf(k) === 0) return t(REASON_LABEL[k]);
  return r;
}
const EMPTY_HTML = document.getElementById('empty').innerHTML;
/* Model 3/Y (HW3) 只有 4 路: front / back / left_repeater / right_repeater
   Model S/X 与 HW4 车型才有 6 路 (含 left_pillar / right_pillar)
   页面按每个事件实际的文件数自适应, 不写死路数 */
const CAM_NAME = { front:'前视', back:'后视', left_repeater:'左B柱', right_repeater:'右B柱',
                   left_pillar:'左前翼', right_pillar:'右前翼' };
/* 排列顺序按「位置成对」：
   4 路(3/Y)      第1排 前视 后视 / 第2排 左B柱 右B柱
   6 路(S/X,HW4)  第1排 左前翼 前视 右前翼 / 第2排 左B柱 后视 右B柱
   这样左右对称, 前后同一排, 一眼能看出方位 */
const CAM_ORDER_4 = ['front','back','left_repeater','right_repeater','left_pillar','right_pillar'];
const CAM_ORDER_6 = ['left_pillar','front','right_pillar','left_repeater','back','right_repeater'];
function camLabel(c) { return t(CAM_NAME[c] || c || '画面'); }
function fmtFull(n) {
  const m = (n || '').match(/^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})/);
  return m ? `${m[1]}/${m[2]}/${m[3]} ${m[4]}:${m[5]}:00` : n;
}
/* 事件展示时间: 有 event.json 就用触发时刻, 否则退回目录名
   (目录名是录制收尾时间, 常在触发之后几十秒, 直接显示会让人以为定位错了) */
function evTime(ev) {
  const m = String((ev && ev.meta && ev.meta.timestamp) || '')
    .match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/);
  if (m) return `${m[1]}/${m[2]}/${m[3]} ${m[4]}:${m[5]}:${m[6]}`;
  return fmtFull(ev && ev.name);
}
function camShort(c) {
  const m = {front:'前',back:'后',left_repeater:'左',right_repeater:'右',left_pillar:'左',right_pillar:'右'};
  return m[c] || (camLabel(c) || '画').slice(0, 1);
}
function toggleDetail() {
  const r = document.getElementById('ic-rows'), b = document.getElementById('ic-fold');
  const open = r.classList.toggle('open');
  b.textContent = open ? '收起详细数据 ⌃' : '展开详细数据 ⌄';
  layoutPlayer();
}
function fmtName(n) {
  const m = (n || '').match(/^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})/);
  return m ? m[2] + '-' + m[3] + ' ' + m[4] + ':' + m[5] : n;
}
function camSort(vs) {
  const order = vs.length > 4 ? CAM_ORDER_6 : CAM_ORDER_4;
  return vs.slice().sort((a, b) => {
    const ia = order.indexOf(a.cam), ib = order.indexOf(b.cam);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
}
/* 事件目录里通常有多组片段 (每分钟一组, 每组 4~6 路), 按组切开 */
function clipKeyOf(v) {
  const f = v.f || v.url.split('/').pop();
  return f.replace(/\.mp4$/i, '').replace(/-[^-]+$/, '');
}
function groupVideos(vids) {
  const m = new Map();
  for (const v of camSort(vids || [])) {
    const k = clipKeyOf(v);
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(v);
  }
  return [...m.keys()].sort().map(k => ({ key: k, vids: m.get(k) }));
}
function curVids() { return (curClips[curClipIx] || { vids: [] }).vids; }
function switchClip(i) {
  if (!curClips[i]) return;
  curClipIx = i;
  pendSeek = 0;          // 手动切段就从头播, 不要沿用触发点定位
  renderClip();
}
function gridDims(n) {
  if (n <= 1) return [1, 1];
  if (n === 2) return [2, 1];
  if (n <= 4) return [2, 2];
  if (n <= 6) return window.innerWidth <= 700 ? [2, 3] : [3, 2];
  const c = window.innerWidth <= 700 ? 2 : 3;
  return [c, Math.ceil(n / c)];
}

/* 页面一打开就把「最可能点开的几路」按当前画质提交后台转码, 只对哨兵/手动保存。
   行车记录不预热: 片段每分钟新增、很快滚动删除, 预转的缓存立刻作废, 还会让
   SoC 长期满载高温。真点开时由 /media 按需后台转码, 先发首帧不阻塞。 */
function prekickList() {
  /* 列表页不再提交完整转码; 归档视频的 10 秒预缓冲由服务端空闲循环统一处理。 */
}

async function load() {
  data = await (await fetch('/api/events')).json();
  const tabs = document.getElementById('tabs');
  tabs.innerHTML = '';
  const liveOpen = document.getElementById('livep').classList.contains('open');
  for (const c of Object.keys(data)) {
    const b = document.createElement('button');
    b.className = 'tab' + (!liveOpen && c === currentCat ? ' active' : '');
    b.innerHTML = `<span class="tl">${t(CATS_NAME[c] || c)}</span><span class="tn">${data[c].length}</span>`;
    b.onclick = () => { document.querySelectorAll('.tab').forEach(t => t.classList.remove('active')); b.classList.add('active'); currentCat = c; reasonFilter = 'all'; dateFilter = 'all'; closeLive(); render(c); prekickList(); };
    tabs.appendChild(b);
  }
  /* 第 4 个页签: 实时预览 (与分类页签同级) */
  const lv = document.createElement('button');
  lv.className = 'tab' + (liveOpen ? ' active' : '');
  lv.id = 'tab-live';
  lv.innerHTML = `<span class="tl">${t('实时预览')}</span>`;   // 与其它页签同结构 (单行分段控件里才不会错位)
  lv.onclick = () => { document.querySelectorAll('.tab').forEach(x => x.classList.remove('active')); lv.classList.add('active'); openLive(); };
  tabs.appendChild(lv);
  document.getElementById('stat').textContent = `${t('归档')} ${Object.values(data).reduce((a, v) => a + v.length, 0)} ${t('条')}`;
  lastSig = sigOf(data);
  renderQSel();
  render(currentCat);
  openDeepLink();
  prekickList();
}

/* 支持 ?ev=SentryClips/2026-11-04_12-30-00 直接打开某个事件 */
function openDeepLink() {
  const q = new URLSearchParams(location.search);
  /* ?date=2026-11-03 只看某一天 */
  const qd = q.get('date');
  if (/^\d{4}-\d{2}-\d{2}$/.test(qd || '')) { dateFilter = qd; render(currentCat); }
  /* ?cat=SavedClips 直接切到某个分类 */
  const qc = q.get('cat');
  if (qc && Object.keys(data).includes(qc)) {
    const tabs = document.getElementById('tabs');
    [...tabs.children].forEach(b => b.classList.remove('active'));
    const idx = Object.keys(data).indexOf(qc);
    if (tabs.children[idx]) tabs.children[idx].classList.add('active');
    currentCat = qc; reasonFilter = 'all'; render(qc);
  }
  const m = q.get('ev');
  if (!m) return;
  const keys = Object.keys(data);
  for (const c of keys) {
    const ev = (data[c] || []).find(e => e.name === m || (c + '/' + e.name) === m);
    if (!ev) continue;
    const tabs = document.getElementById('tabs');
    [...tabs.children].forEach(b => b.classList.remove('active'));
    const idx = keys.indexOf(c);
    if (tabs.children[idx]) tabs.children[idx].classList.add('active');
    currentCat = c; reasonFilter = 'all'; render(c); openPlayer(ev);
    const cam = new URLSearchParams(location.search).get('cam');
    if (cam) setCam(cam);
    if (q.get('exp') === '1') setTimeout(openExport, 600);
    return;
  }
}

function sigOf(d) {
  return Object.keys(d).map(c => c + ':' + d[c].map(e => e.name + '/' + e.videos.length).join(',')).join('|');
}

/* 容量条配色: <30% 绿 / 30%~85% 蓝 / >85% 红 (三行同规则) */
function storColor(pct) {
  if (!(pct > 0)) return '#4cc38a';
  if (pct > 85) return '#e8443f';
  if (pct < 30) return '#4cc38a';
  return '#2f6ee0';
}

/* 实时同步状态 + 新片段自动出现 */
async function refreshLive() {
  let live = null;
  try { live = await (await fetch('/api/live')).json(); } catch (e) { return; }
  const dot = document.getElementById('livedot'), txt = document.getElementById('livetxt');
  if (live.running) {
    dot.style.background = '#4cc38a';
    if (live.pending > 0) txt.textContent = `${t('实时同步中')} · ${live.pending} ${t('待确认')}`;
    else if (live.ago !== null && live.ago !== undefined) txt.textContent = `${t('实时同步中')} · ${live.ago}s`;
    else txt.textContent = t('实时同步中');
  } else {
    dot.style.background = '#e8443f';
    txt.textContent = t('同步服务未运行');
  }
  // 存储卡: 默认只显示虚拟U盘, 点右下角小箭头再展开归档区/总占用
  const sw = document.getElementById('storwrap');  const dk = live.disk;
  if (dk && dk.disk_total > 0) {
    const GB = 1073741824;
    const gb = n => {
      if (!n || n < 0) return '0MB';
      return n >= GB ? (n / GB).toFixed(1) + 'GB' : Math.round(n / 1048576) + 'MB';
    };
    const tset = (v, used, total, bar) => {
      document.getElementById(v).textContent = total > 0 ? gb(used) + ' / ' + gb(total) : gb(used);
      const pct = total > 0 ? Math.min(100, used / total * 100) : 0;
      const el = document.getElementById(bar);
      el.style.width = pct.toFixed(1) + '%';
      el.style.background = storColor(pct);
    };
    sw.style.display = '';
    // 虚拟U盘: 卷内实际写入 / 镜像标称容量
    // (img_real 是镜像在宿主盘上的预分配占用, 几乎等于标称容量, 永远 100% 不直观)
    tset('storvusb', dk.img_used != null ? dk.img_used : dk.img_real, dk.img_nominal,
         'storvusbbar');
    const vu = document.getElementById('storvusb');
    if (vu) vu.title = t('车机 U 盘里已写入的数据 / 车机看到的容量');
    // 归档区: 已归档 / 用户分配额度; 未设额度才回退到已归档+盘剩余
    const arcTot = dk.arc_total > 0 ? dk.arc_total : (dk.arc_used || 0) + (dk.arc_free || 0);
    tset('storarc', dk.arc_used, arcTot, 'storarcbar');
    const ia = document.getElementById('storarc');
    if (ia) ia.title = t('归档已用 / 分配额度；物理盘容量与剩余空间请看总占用');
    // 总占用: 整盘已用 / 整盘容量 (三行统一按 storColor 的占用比例取色)
    tset('stortot', dk.disk_used, dk.disk_total, 'stortotbar');
    // 系统状态 (同一折叠区): 三等分指标格, 标签在上/数值在下; 温度异常时染色
    const sy = live.sys, syEl = document.getElementById('storsys');
    if (syEl) {
      const cell = (k, v, color) =>
        '<div class="syscell"><span class="k">' + k + '</span>' +
        '<span class="v"' + (color ? ' style="color:' + color + '"' : '') + '>' + v + '</span></div>';
      const tp = (sy && sy.cpu_temp != null) ? sy.cpu_temp : null;
      const tc = tp == null ? '' : tp > 70 ? '#e8443f' : tp < 40 ? '#4cc38a' : '';
      const mem = (sy && sy.mem_total > 0)
        ? gb(sy.mem_used) + '<span class="u">/' + gb(sy.mem_total) + '</span>' : '—';
      syEl.innerHTML =
        cell('温度', tp != null ? tp + '°C' : '—', tc) +
        cell('CPU', (sy && sy.cpu_pct != null) ? sy.cpu_pct + '%' : '—') +
        cell('内存', mem);
    }
  } else {
    sw.style.display = 'none';
  }
  // 事件有变化时无缝重绘 (不打断播放器)
  try {
    const d = await (await fetch('/api/events')).json();
    const s = sigOf(d);
    if (s !== lastSig) {
      lastSig = s; data = d;
      const tabs = document.getElementById('tabs');
      [...tabs.children].forEach((b, i) => {
        const c = Object.keys(d)[i];
        if (c) b.innerHTML = `<span class="tl">${t(CATS_NAME[c] || c)}</span><span class="tn">${d[c].length}</span>`;
      });
      document.getElementById('stat').textContent = `${t('归档')} ${Object.values(d).reduce((a, v) => a + v.length, 0)} ${t('条')}`;
      if (!document.getElementById('player').classList.contains('open')) render(currentCat);
      prekickList();   // 新的哨兵/保存事件刚同步过来时, 按当前画质提交后台预转
    }
  } catch (e) {}
}
refreshLive();
setInterval(refreshLive, 10000);

/* 缩略图: 服务端抽帧的静态图, 原生懒加载; 不再用 <video> 预览 (会把设备和解码器一起拖死) */
function reasonOf(ev) {
  return (ev.meta && ev.meta.reason) || 'unknown';
}
/* 事件目录名以 YYYY-MM-DD_HH-MM-SS 开头, 取前 10 位作为日期 */
/* 哨兵事件: reason 以 sentry_ 开头; camera 字段只有哨兵触发才有意义 */
function isSentryEv(md) {
  return String((md || {}).reason || '').indexOf('sentry_') === 0;
}
/* event.json 的 camera 编号 -> 片段文件后缀 (社区公认映射: 0前 3左前 4右前 5左B 6右B 7后) */
const CAM_IDX = {0:'front', 3:'left_pillar', 4:'right_pillar', 5:'left_repeater', 6:'right_repeater', 7:'back'};
/* 片段组 key (YYYY-MM-DD_HH-MM-SS) -> 墙钟毫秒; 车机片段名与 event.json timestamp 同一时基, 直接比较 */
function clipEpoch(k) {
  const m = String(k || '').match(/^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})/);
  return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime() : 0;
}
/* 哨兵封面: 触发摄像头 + 触发那一帧; 找不到对应片段/摄像头返回 null 回落默认封面 */
function sentryThumbSrc(ev, groups) {
  const md = ev.meta || {};
  const camKey = CAM_IDX[+md.camera];
  const m = String(md.timestamp || '').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/);
  if (!camKey || !m) return null;
  const tg = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime();
  if (!tg) return null;
  for (const g of groups) {                       // groups 已按片段开始时间升序
    const s = clipEpoch(g.key);
    if (!s || tg < s || tg > s + 70e3) continue;  // 触发时刻落在这 1 分钟片段内
    const v = g.vids.find(x => x.cam === camKey);
    if (!v) return null;                          // 触发摄像头该分钟没录到, 回落
    return v.url.replace('/media/', '/thumb/') + '?t=' + Math.max(0, Math.round((tg - s) / 1000));
  }
  return null;
}
function dateOf(ev) {
  const m = String(ev.name || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? m[1] + '-' + m[2] + '-' + m[3] : '';
}
/* 官方App哨兵分类: 警觉 / 车门拉动 / 遭遇袭击 (reason 前缀映射, 未知 sentry_ 值归入警觉) */
function reasonTab(r) {
  if (r.indexOf('sentry_panic') === 0 || r.indexOf('sentry_aware_accel') === 0) return 'panic';
  if (r.indexOf('sentry_aware_door') === 0 || r.indexOf('sentry_aware_handle') === 0) return 'door';
  return 'aware';
}
const SENTRY_TABS = [['all', '全部'], ['aware', '哨兵警觉'], ['door', '车门拉动'], ['panic', '遭遇袭击']];
/* 筛选匹配: 哨兵分类按官方三分类的 key 匹配, 其他分类按原始 reason 精确匹配 */
function matchReason(cat, ev) {
  if (reasonFilter === 'all') return true;
  if (cat === 'SentryClips') return reasonTab(reasonOf(ev)) === reasonFilter;
  return reasonOf(ev) === reasonFilter;
}
/* 两行筛选: 触发原因 / 日期, 互为主次 (计数按对方的筛选结果算) */
function renderFilters(cat) {
  const evs = data[cat] || [];
  const rbox = document.getElementById('filters'), dbox = document.getElementById('dfilters');
  const byDate = dateFilter === 'all' ? evs : evs.filter(ev => dateOf(ev) === dateFilter);
  const byReason = reasonFilter === 'all' ? evs : evs.filter(ev => matchReason(cat, ev));

  // 原因筛选在新分类里可能不存在, 自动回落避免"空列表卡死"; 日期允许选到没有事件的那天(会显示空态提示)
  if (reasonFilter !== 'all' && !evs.some(ev => matchReason(cat, ev))) reasonFilter = 'all';

  if (cat === 'SentryClips') {
    // 官方App样式: 固定分类行常驻, 计数为 0 也显示 (和车机/官方App一致)
    const cnt = { all: byDate.length };
    byDate.forEach(ev => { const t = reasonTab(reasonOf(ev)); cnt[t] = (cnt[t] || 0) + 1; });
    rbox.className = 'filters show';
    rbox.innerHTML = SENTRY_TABS.map(([k, label]) =>
      `<button class="chip${k === reasonFilter ? ' on' : ''}" onclick="setReason('${k}')">${t(label)}<span class="n">${cnt[k] || 0}</span></button>`
    ).join('');
  } else {
    const rcnt = {};
    byDate.forEach(ev => { const r = reasonOf(ev); rcnt[r] = (rcnt[r] || 0) + 1; });
    const rkeys = Object.keys(rcnt).sort((a, b) => rcnt[b] - rcnt[a]);
    if (rkeys.length < 2) { rbox.className = 'filters'; rbox.innerHTML = ''; }
    else {
      rbox.className = 'filters show';
      const items = [['all', t('全部'), byDate.length]].concat(
        rkeys.map(k => [k, reasonLabel(k) !== k ? reasonLabel(k) : t('未标注原因'), rcnt[k]]));
      rbox.innerHTML = '<span class="flab">' + t('原因') + '</span>' + items.map(([k, label, n]) =>
        `<button class="chip${k === reasonFilter ? ' on' : ''}" onclick="setReason('${k}')">${label}<span class="n">${n}</span></button>`
      ).join('');
    }
  }

  const dcnt = {};
  byReason.forEach(ev => { const d = dateOf(ev); if (d) dcnt[d] = (dcnt[d] || 0) + 1; });
  if (dateFilter !== 'all' && !/^\d{4}-\d{2}-\d{2}$/.test(dateFilter)) dateFilter = 'all';
  const alldays = [...new Set(evs.map(dateOf).filter(Boolean))].sort().reverse();
  let days = alldays.filter(d => dcnt[d] > 0 || d === dateFilter);
  // 自选日期可能当天没有事件, 仍然把选中的那天显示出来, 方便点回「全部日期」
  if (dateFilter !== 'all' && !days.includes(dateFilter)) days = [dateFilter].concat(days);
  if (!alldays.length && dateFilter === 'all') { dbox.className = 'filters'; dbox.innerHTML = ''; return; }
  dbox.className = 'filters show';
  const items = [['all', t('全部日期'), byReason.length]].concat(
    days.map(d => [d, d.slice(5).replace('-', '/'), dcnt[d] || 0]));
  dbox.innerHTML = '<span class="flab">' + t('日期') + '</span>' + items.map(([k, label, n]) =>
    `<button class="chip d${k === dateFilter ? ' on' : ''}" onclick="setDate('${k}')">${label}<span class="n">${n}</span></button>`
  ).join('') + '<button class="chip pick" onclick="pickDate()" title="' + t('选择日期…') + '">' + t('选择日期…') + '</button>';
}
/* 原生日期选择器: 分类里只有一天时也能翻到别的日期 */
function pickDate() {
  const inp = document.getElementById('dpick');
  if (!inp) return;
  const t = new Date();
  inp.max = t.getFullYear() + '-' + String(t.getMonth() + 1).padStart(2, '0') + '-' +
    String(t.getDate()).padStart(2, '0');
  inp.value = dateFilter !== 'all' ? dateFilter : '';
  try { if (inp.showPicker) { inp.showPicker(); return; } } catch (e) {}
  inp.click();
}
function setReason(k) {
  reasonFilter = k;
  render(currentCat);
}
function setDate(k) {
  dateFilter = k;
  render(currentCat);
}
/* 缩略图失败多半是临时的 (磁盘满/片段刚同步完还没落稳), 自动重试两次再显示占位图 */
function thumbErr(img) {
  const n = +(img.dataset.r || 0);
  if (n < 2) {
    img.dataset.r = n + 1;
    setTimeout(() => { img.src = img.src.split('?')[0] + '?r=' + (n + 1); }, n ? 8000 : 2500);
    return;
  }
  img.parentNode.innerHTML = '<div class="ph">🎞</div>';
}
/* 日期分组小标题: 今天/昨天/M月D日 */
function dheadLabel(d) {
  const now = new Date(), today = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
  const y = new Date(now.getTime() - 864e5), yd = y.getFullYear() + '-' + String(y.getMonth() + 1).padStart(2, '0') + '-' + String(y.getDate()).padStart(2, '0');
  const m = d.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return d;
  if (d === today) return t('今天');
  if (d === yd) return t('昨天');
  if (LANG === 'zh') return (+m[2]) + '月' + (+m[3]) + '日';
  try { return new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString(LANG, { month: 'short', day: 'numeric' }); }
  catch (e) { return d.slice(5); }
}
function render(cat) {
  const g = document.getElementById('grid'), e = document.getElementById('empty');
  g.innerHTML = '';
  renderFilters(cat);
  let evs = data[cat] || [];
  evs = evs.filter(ev => matchReason(cat, ev));
  if (dateFilter !== 'all') evs = evs.filter(ev => dateOf(ev) === dateFilter);
  e.style.display = evs.length ? 'none' : 'block';
  if (!evs.length) {
    e.innerHTML = (reasonFilter !== 'all' || dateFilter !== 'all')
      ? '<div class="big">🔍</div><div>' + t('该筛选下暂无事件') + '<br><small style="font-size:12px">' + t('换个日期或点「全部」查看本分类所有事件') + '</small></div>'
      : EMPTY_HTML;
  }
  let prevDay = null;
  for (const ev of evs) {
    const day = dateOf(ev);
    if (day && day !== prevDay) {           // 日期分组小标题 (像官方App的"下午 14:00-17:59 · 3条")
      const n = evs.filter(x => dateOf(x) === day).length;
      const h = document.createElement('div'); h.className = 'dhead';
      h.innerHTML = '<b>' + dheadLabel(day) + '</b><span class="n">' + n + ' ' + t('条') + '</span>';
      g.appendChild(h);
      prevDay = day;
    }
    const card = document.createElement('div'); card.className = 'card';
    const groups = groupVideos(ev.videos);
    const vids = camSort(groups.length ? groups[groups.length - 1].vids : []);
    let th;
    if (vids.length) {
      /* 哨兵事件: 用触发摄像头在触发那一帧当封面; 其他/回落: 前摄像头第1秒 */
      const src = sentryThumbSrc(ev, groups) ||
        (vids.find(v => v.cam === 'front') || vids[0]).url.replace('/media/', '/thumb/');
      th = `<div class="thumb"><img loading="lazy" decoding="async" src="${src}" alt="" onerror="thumbErr(this)"><span class="cnum">${vids.length} ${t('路')}</span></div>`;
    } else {
      th = `<div class="thumb"><div class="ph">🎞</div></div>`;
    }
    const mm = ev.meta || {};
    /* 标题: 触发原因·触发摄像头 (哨兵), 否则分类名 */
    let title = t(CATS_NAME[cat] || cat);
    if (mm.reason) {
      title = reasonLabel(mm.reason) || mm.reason;
      if (isSentryEv(mm) && mm.camera) {
        const ck = CAM_IDX[+mm.camera];
        if (ck) title += ' · ' + camLabel(ck);
      }
    }
    /* 列表时间优先用 event.json 的触发时刻, 与点进去后播放器标题一致
       (目录名是录制收尾时间, 常比触发晚几十秒) */
    const tsM = String(mm.timestamp || '').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    const tm = tsM ? tsM[4] + ':' + tsM[5]
                   : (ev.name.match(/_(\d{2}-\d{2})/) || [,''])[1].replace('-', ':');
    const tmTxt = tm ? tm : fmtName(ev.name);
    const extra = (mm.city ? ' · ' + mm.city : '') + (mm.street ? ' ' + mm.street : '');
    const dayTxt = dateFilter === 'all' && day ? day.slice(5).replace('-', '/') + ' · ' : '';
    const mb = ev.size / 1048576;
    const szTxt = mb >= 1 ? mb.toFixed(1) + ' MB' : (mb * 1024).toFixed(0) + ' KB';
    card.innerHTML = th + `<div class="meta"><div class="l1"><span class="rt" title="${title}">${title}</span><span class="tm">${tmTxt}${extra}</span></div><div class="l2"><span>${dayTxt}${vids.length} ${t('路画面')}</span><span class="sz">${szTxt}</span></div></div>`;
    card.onclick = () => openPlayer(ev);
    g.appendChild(card);
  }
  applyLang();
}

function layoutPlayer() {
  const vg = document.getElementById('vgrid');
  if (vg.querySelector('.vcell.focused')) return;  // 单路放大时保持满屏
  const n = vg.children.length;
  if (!n) return;
  const d = gridDims(n);
  vg.style.gridTemplateColumns = `repeat(${d[0]},1fr)`;
  // 显式像素行高: 不依赖 CSS aspect-ratio (老版 iOS Safari 不支持时格子会塌陷/视频层溢出遮挡)
  const w = vg.clientWidth || 0;
  if (w > 0) {
    const gap = 3;
    const cw = (w - gap * (d[0] - 1)) / d[0];
    /* 单路: 按画面真实比例 (哨兵片源多为 4:3), 不然 16:9 的格子会把上下裁掉 */
    let ar = 9 / 16;
    if (n === 1) {
      const v0 = vg.querySelector('video');
      if (v0 && v0.videoWidth > 0 && v0.videoHeight > 0) ar = v0.videoHeight / v0.videoWidth;
    }
    vg.style.gridAutoRows = Math.round(cw * ar) + 'px';
  }
}
/* 点击任意一路: 单路铺满; 再点一次(或 Esc)恢复多路 */
function focusCell(cell) {
  const vg = document.getElementById('vgrid');
  const cells = [...vg.children];
  if (cells.length < 2) return;     // 单路模式已经是满宽, 再放大没有意义
  const wasFocused = cell.classList.contains('focused');
  cells.forEach(c => { c.classList.remove('focused'); c.style.display = ''; });
  if (wasFocused) { layoutPlayer(); return; }
  cell.classList.add('focused');
  cells.forEach(c => { if (c !== cell) c.style.display = 'none'; });
  vg.style.gridTemplateColumns = '1fr';
  vg.style.gridTemplateRows = '1fr';
}
/* 本次渲染要定位到的秒数 (触发时刻), 0 = 从头播 */
let pendSeek = 0;
/* 找出 event.json 触发时刻落在哪一段, 返回 {ix, off}; 对不上返回 null。
   一组哨兵片段通常是「触发前 1 分钟 + 触发 + 后续几分钟」, 触发点在中间某段,
   取 start <= 触发时刻 且最接近的那段 (片段实长约 60 秒, 上限放宽到 70 秒)。*/
function triggerClip(ev, clips) {
  const m = String((ev.meta || {}).timestamp || '').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/);
  if (!m) return null;
  const tg = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime();
  if (!tg) return null;
  let best = null;
  (clips || []).forEach((c, i) => {
    const s = clipEpoch(c.key);
    if (!s || s > tg) return;
    const off = (tg - s) / 1000;
    if (off <= 70 && (!best || s > best.s)) best = { ix: i, off: off, s: s };
  });
  return best;
}
/* 画面模式: 'all' = 全览 (所有方位同屏), 其他 = 单路 (只加载这一路的视频)。
   默认是触发摄像头那一路 —— 单路既秒开又省流量, 其他方位等用户点按钮再加载。 */
let camSel = 'all';
function triggerCam(ev) {
  const md = (ev && ev.meta) || {};
  const c = md.camera;
  if (c === undefined || c === null || String(c).trim() === '' || !isSentryEv(md)) return '';
  return CAM_IDX[+c] || '';
}
function pickDefaultCam() {
  const vs = curVids();
  const tc = triggerCam(cur);
  if (tc && vs.some(v => (v.cam || '') === tc)) return tc;
  const s = camSort(vs);
  return s.length ? (s[0].cam || '') : 'all';   // 没有触发画面信息就用第一路(通常是前视)
}
/* 单路 ↔ 全览切换: 保留当前进度, 只加载被选中的那一路 */
function setCam(c) {
  if (c === camSel) return;
  const old = document.querySelector('#vgrid video');
  const t0 = old ? (old.currentTime || 0) : 0;
  camSel = c;
  pendSeek = t0;          // 换画面不回到片头, 接着刚才的位置播
  renderClip();
}
function renderCamBar() {
  const bar = document.getElementById('cambar');
  const all = camSort(curVids());
  if (!bar) return;
  /* 只有一路画面时没必要显示选择条 */
  if (all.length < 2) { bar.className = 'cambar'; bar.innerHTML = ''; return; }
  const tc = triggerCam(cur);
  bar.className = 'cambar show';
  bar.innerHTML = all.map(v => {
    const c = v.cam || '';
    const isTrig = !!c && c === tc;
    return `<button class="${camSel === c ? 'on' : ''}${isTrig ? ' trig' : ''}"` +
      (isTrig ? ' title="触发画面"' : '') + ` onclick="setCam('${c}')">${camLabel(c)}</button>`;
  }).join('') +
    `<button class="${camSel === 'all' ? 'on' : ''}" onclick="setCam('all')">${t('全览')}</button>`;
}
function openPlayer(ev) {
  cur = ev;
  startPlaybackSession();
  curClips = groupVideos(ev.videos);
  kicked = new Set();      // 新事件重新计算预转范围
  /* 默认定位到触发时刻所在那一段, 并停在触发前 5 秒 —— 以前固定取最后一段,
     所以多段事件点进去常常是「人已经走了」的那一分钟 */
  const hit = triggerClip(ev, curClips);
  curClipIx = hit ? hit.ix : (curClips.length ? curClips.length - 1 : 0);
  pendSeek = hit ? Math.max(0, hit.off - 5) : 0;
  camSel = pickDefaultCam();     // 默认单路: 触发摄像头
  renderClip();
}
/* 播放器打开/切段时, 把相邻段的当前清晰度让服务端提前转好。
   预热只覆盖触发段±1 组, 但用户会点任意片段芯片 —— 现看现转要每路十几秒,
   提前一分钟踢一脚, 切过去基本就是秒开。 */
let kicked = new Set();
function kickGroup(ix) {
  const c = curClips[ix];
  if (!c || curQ === 'orig') return;
  const tag = curQ + ' ' + c.key + ' ' + camSel;
  if (kicked.has(tag)) return;
  kicked.add(tag);
  /* 单路模式只预转被选中的那一路, 其他方位等用户点按钮再说 */
  const vids = camSel === 'all' ? camSort(c.vids)
                                : c.vids.filter(v => (v.cam || '') === camSel);
  const paths = vids.map(v => v.url);
  if (!paths.length) return;
  try { fetch('/api/kick', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({paths: paths, q: curQ, sid: playbackSid})}).catch(() => {}); } catch (e) {}
}
function renderClip() {
  const ev = cur;
  const seekTo = pendSeek;   // 本次渲染消费掉定位点, 之后换语言等重渲染不会又跳一次
  pendSeek = 0;
  const clip = curClips[curClipIx] || { key: '', vids: [] };
  const vg = document.getElementById('vgrid'); vg.innerHTML = '';
  /* 单路模式: 只这一路进 DOM —— 没被选中的方位连请求都不会发出去 */
  const allVids = camSort(clip.vids);
  let shown = allVids;
  if (camSel !== 'all') {
    const one = allVids.filter(v => (v.cam || '') === camSel);
    if (one.length) shown = one;
    else camSel = 'all';          // 这一段没有该方位, 退回全览
  }
  shown.forEach(v => {
    const cell = document.createElement('div'); cell.className = 'vcell';
    cell.dataset.cam = v.cam || '';
    const vid = document.createElement('video');
    /* preload 用 metadata 而不是 auto: 4 路同时 auto 会各拉整段 3.7MB (合计 15MB),
       在盒子 4G 上行这种窄链路上互相抢, 反而谁都要缓冲半天。
       只要元数据就能定位到触发时刻, 点播放时再按需拉那一小段。*/
    vid._baseUrl = v.url;
    vid._fullUrl = qUrl(v.url);
    let vsrc = vid._fullUrl;
    if (!isLanNet && curQ === '360p' && seekTo < 9) {
      vsrc += (vsrc.indexOf('?') >= 0 ? '&' : '?') + 'preview=10';
      vid._wantPreview = true;
      vid.addEventListener('loadedmetadata', () => {
        if (vid.duration && vid.duration <= 10.5) vid._preview = true;
        else vid._wantPreview = false;
      });
    }
    vid.src = vsrc; vid.muted = true; vid.defaultMuted = true; vid.preload = 'metadata';
    /* 每格加载状态: 转码/缓冲时显示提示, 避免黑屏让人以为坏了 */
    const cl = document.createElement('div'); cl.className = 'cload';
    cl.innerHTML = '<span class="spin"></span><span>缓冲中…</span>';
    const clDone = () => { cl.style.display = 'none'; };
    vid.addEventListener('loadeddata', clDone);
    vid.addEventListener('playing', clDone);
    vid.addEventListener('error', () => {
      cl.className = 'cload err';
      cl.innerHTML = '<span>' + t('加载失败, 点其他片段再试') + '</span>';
    });
    vid.addEventListener('waiting', () => { cl.style.display = ''; });
    /* 注意: 这里不再往 #qhint 塞「正在转码」的提示 —— 那段文案是 2.8.x 早期「点开才转码」的残留,
       现在新事件触发段已经预热好了, 中途一次带宽抖动也会触发 waiting, 提示纯属误导。
       每格自己有「缓冲中…」遮罩, 足够表达状态; #qhint 只留给手动切清晰度时用。
       现在 /media 未命中画质缓存会先给原画 + 后台转码, 首帧不再干等十几秒。*/
    vid.addEventListener('canplay', () => { document.getElementById('qhint').style.display = 'none'; });
    vid.setAttribute('muted', ''); vid.setAttribute('playsinline', '');
    vid.setAttribute('webkit-playsinline', ''); vid.setAttribute('x5-playsinline', '');
    /* 触发段: metadata 一到就跳到触发前几秒, 不然会先从片段开头播一遍 */
    if (seekTo > 0) {
      const ap = () => {
        const d0 = isFinite(vid.duration) ? vid.duration : 0;
        try { vid.currentTime = d0 ? Math.min(seekTo, Math.max(0, d0 - 0.4)) : seekTo; } catch (e) {}
      };
      vid.addEventListener('loadedmetadata', ap);
      if (vid.readyState >= 1) ap();
    }
    const lb = document.createElement('span'); lb.className = 'clabel'; lb.textContent = camShort(v.cam);
    cell.appendChild(vid); cell.appendChild(cl); cell.appendChild(lb);
    cell.onclick = () => focusCell(cell);
    /* 单路: 拿到真实宽高后按画面比例重算格子高度 (4:3 片源不再被裁) */
    if (shown.length === 1) {
      vid.addEventListener('loadedmetadata', () => { if (vg.children.length === 1) layoutPlayer(); });
    }
    vg.appendChild(cell);
  });
  vg.classList.toggle('one', shown.length === 1);   // 单路: 交给 JS 按画面比例定行高
  renderCamBar();
  document.getElementById('ic-time').textContent = evTime(ev);
  const pt = document.getElementById('ptitle');
  if (pt) pt.textContent = t(CATS_NAME[currentCat] || currentCat) + ' · ' + evTime(ev);
  document.getElementById('ic-cat').textContent = t(CATS_NAME[currentCat] || currentCat);
  const md0 = ev.meta || {};
  document.getElementById('ic-big').textContent =
    (md0.reason && (reasonLabel(md0.reason) || md0.reason)) || CATS_NAME[currentCat] || currentCat;
  const mb = (ev.size || 0) / 1048576;
  const camTxt = camSel === 'all'
    ? (shown.length + ' 路同屏')
    : (camLabel(camSel) + ' 单路' + (clip.vids.length > shown.length ? ' (共 ' + clip.vids.length + ' 路可选)' : ''));
  document.getElementById('ic-sub').innerHTML = camTxt + ' · <span id="ic-dur">--:--</span>' + (mb >= 0.05 ? ' · ' + (mb >= 1 ? mb.toFixed(1) + ' MB' : Math.round(mb * 1024) + ' KB') : '');
  const cb = document.getElementById('clipbar');
  if (curClips.length > 1) {
    const hitClip = triggerClip(ev, curClips);
    cb.classList.add('show');
    cb.innerHTML = '<span class="ick" style="min-width:auto;align-self:center">片段</span>' +
      curClips.map((c, i) => {
        const t = (c.key.split('_')[1] || c.key).replace(/-/g, ':');
        const isTrig = hitClip && hitClip.ix === i;
        return `<button class="${i === curClipIx ? 'on' : ''}${isTrig ? ' trig' : ''}"` +
          (isTrig ? ' title="触发时刻在这段"' : '') +
          ` onclick="switchClip(${i})">${t}</button>`;
      }).join('');
  } else {
    cb.classList.remove('show');
    cb.innerHTML = '';
  }
  const md = ev.meta || {};
  let rh = '';
  rh += '<div data-k="time"><span class="ick">时间</span>' + (md.timestamp ? md.timestamp.replace('T', ' ') : fmtFull(ev.name)) + '</div>';
  if (md.city) rh += '<div data-k="city"><span class="ick">城市</span>' + md.city + '</div>';
  if (md.street) rh += '<div data-k="street"><span class="ick">位置</span>' + md.street + '</div>';
  if (md.est_lat && md.est_lon) rh += '<div data-k="coord"><span class="ick">坐标</span>' + md.est_lat + ', ' + md.est_lon + '</div>';
  if (md.reason) rh += '<div><span class="ick">触发原因</span>' + (reasonLabel(md.reason) || md.reason) + '</div>';
  /* camera 字段只有哨兵事件有意义; 手动保存等也会带 camera:"0" */
  if (md.camera && isSentryEv(md)) { const cn = CAM_IDX[+md.camera]; rh += '<div data-k="camera"><span class="ick">触发画面</span>' + (cn ? camLabel(cn) : '摄像头') + ' #' + md.camera + '</div>'; }
  if (md.campaign_id) rh += '<div><span class="ick">活动ID</span>' + md.campaign_id + '</div>';
  rh += '<div><span class="ick">画面</span>' + clip.vids.length + ' 路</div>';
  if (curClips.length > 1) rh += '<div><span class="ick">片段</span>共 ' + curClips.length + ' 段, 当前第 ' + (curClipIx + 1) + ' 段</div>';
  rh += camSort(clip.vids).map(v => '<div><span class="ick">' + camLabel(v.cam) + '</span>' + v.url.split('/').pop() + '</div>').join('');
  if (!md.timestamp) rh += '<div><span class="ick">元数据</span>无 event.json（该事件未写入元数据）</div>';
  const rows = document.getElementById('ic-rows');
  rows.innerHTML = rh;
  rows.classList.remove('open');
  document.getElementById('ic-fold').textContent = '展开详细数据 ⌄';
  layoutPlayer();
  document.getElementById('player').classList.add('open');
  requestAnimationFrame(layoutPlayer);  // 可见后再算一次, 保证拿到真实宽度设置像素行高
  const sm = document.getElementById('startmask');
  if ('ontouchstart' in window) { sm.classList.add('show'); }
  playAll();
  kickGroup(curClipIx + 1);   // 前后相邻组提前转码, 切段不再等十几秒
  kickGroup(curClipIx - 1);
  if (syncTimer) clearInterval(syncTimer);
  syncTimer = setInterval(tick, 250);
  const sortedVids = camSort(shown);
  loadTelemetry(sortedVids.length ? sortedVids[0].url : null, md);
}

/* ---------- 行车遥测面板 (SEI, 视频上方) ---------- */
let telT0 = null, TEL_META = {};
function loadTelemetry(url, meta) {
  TEL = null;
  TEL_META = meta || {};
  const p = document.getElementById('tpanel'), card = document.getElementById('infocard');
  p.classList.remove('show', 'plain');
  if (card) card.classList.remove('plain');
  p.classList.add('folded');   // 详细数据默认折叠
  document.getElementById('tp-fold').textContent = '展开详细数据 ⌄';
  document.getElementById('tp-loc').textContent =
    [TEL_META.city, TEL_META.street].filter(Boolean).join(' · ');
  // 触发画面摄像头: 只有哨兵事件显示 (手动保存等也会带无意义的 camera:"0")
  const camTag = document.getElementById('tp-tag');
  if (TEL_META.camera && isSentryEv(TEL_META)) {
    const cn = CAM_IDX[+TEL_META.camera];
    camTag.innerHTML = '触发画面 <b>' + (cn ? camLabel(cn) : '摄像头') + ' #' + TEL_META.camera + '</b>';
    camTag.classList.add('show');
  } else {
    camTag.classList.remove('show');
    camTag.innerHTML = '';
  }
  telT0 = null;
  if (!url) return;
  const m = url.match(/(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})/);
  if (m) telT0 = new Date(+m[1], +m[2]-1, +m[3], +m[4], +m[5], +m[6]);
  // 顶部时间: 优先 event.json 的 timestamp, 否则退回片段文件名里的时间
  const ts = String(TEL_META.timestamp || '').replace('T', ' ').replace(/\.\d+/, '').replace(/Z$/, '').slice(0, 19);
  document.getElementById('tp-date').textContent = ts || (telT0 ? fmtTelDate(telT0) : '—');
  const fp = url.replace('/media/', '/archive/');
  fetch('/api/telemetry?path=' + encodeURIComponent(fp))
    .then(r => r.json())
    .then(d => {
      if (!d.ok || !d.frames || !d.frames.length) { showPlainPanel(); return; }
      TEL = d;
      p.classList.add('show');
      renderHud(d.frames[0]);
      // 事件信息已搬到上方遥测面板, 下方卡片去掉重复项
      ['time', 'city', 'street', 'coord', 'camera'].forEach(k => {
        const el = document.querySelector('#ic-rows > div[data-k="' + k + '"]');
        if (el) el.remove();
      });
      document.getElementById('ic-rows').insertAdjacentHTML('beforeend',
        '<div><span class="ick">刹车占比</span>' + d.brake_ratio + '%</div>' +
        '<div><span class="ick">遥测</span>SEI 元数据 · ' + d.count + ' 帧 @ ' + d.fps + 'fps</div>');
    }).catch(() => showPlainPanel());
}
/* 哨兵/停车片段没有 SEI 遥测: 顶部仍然显示 时间 + 城市·位置, 只是不带车速/挡位 */
function showPlainPanel() {
  const p = document.getElementById('tpanel'), card = document.getElementById('infocard');
  p.classList.add('show', 'plain');
  if (card) card.classList.add('plain');
  ['time', 'city', 'street', 'camera'].forEach(k => {
    const el = document.querySelector('#ic-rows > div[data-k="' + k + '"]');
    if (el) el.remove();
  });
  layoutPlayer();
}
function fmtTelDate(dt) {
  const z = n => (n < 10 ? '0' : '') + n;
  return dt.getFullYear() + '/' + z(dt.getMonth()+1) + '/' + z(dt.getDate()) + ' ' +
    z(dt.getHours()) + ':' + z(dt.getMinutes()) + ':' + z(dt.getSeconds());
}
function renderHud(f) {
  // f: 0=t 1=挡位 2=车速km/h 3=油门% 4=方向盘角度 5=刹车 6=转向灯 7=AP 8=lat 9=lon 10=heading 11=Ax 12=Ay 13=Az
  const q = id => document.getElementById(id);
  q('tp-gear').textContent = f[1];
  q('tp-spd').textContent = Math.max(0, Math.round(f[2]));   // 停车时 SEI 可能给微负值
  q('tp-date').textContent = telT0 ? fmtTelDate(new Date(telT0.getTime() + f[0]*1000)) : '—';
  q('tp-thr-n').textContent = f[3] + '%';
  q('tp-brk').classList.toggle('on', !!f[5]);   // 刹车只有布尔量, 不给百分比
  // 转向灯: HUD 由 CSS 的 tpBlink 动画负责闪 (.on 只表示"打了哪边的灯")
  q('tp-bl').classList.toggle('on', f[6] === 1);
  q('tp-br').classList.toggle('on', f[6] === 2);
  const apNames = { 1: 'FSD', 2: 'AP', 3: 'TACC' };
  // 自动驾驶状态就挂在方向盘那颗图标上 (AP/EAP/FSD 共用同一个方向盘, 不再单独占一个 "AP" 徽标);
  // 启动时橙红渐变, 未启动时灰底, 图标本身按方向盘角度旋转
  const apv = f[7] | 0, st = q('tp-st');
  st.classList.toggle('ap-on', !!apv);
  st.title = '方向盘角度 ' + f[4] + '° · ' + (apv ? ((apNames[apv] || 'AP') + ' 已启动') : '自动驾驶未启动');
  const ang = Math.max(-400, Math.min(400, Number(f[4]) || 0));
  st.querySelector('svg').style.transform = 'rotate(' + ang + 'deg)';
  const md = TEL_META || {};
  q('tp-rows').innerHTML =
    (md.est_lat && md.est_lon ? '<div><span class="k">坐标</span>' + md.est_lat + ', ' + md.est_lon + '</div>' : '') +
    '<div><span class="k">方向盘角度</span>' + f[4] + '°</div>' +
    '<div><span class="k">横向加速度 Ax</span>' + f[11].toFixed(2) + ' m/s²</div>' +
    '<div><span class="k">前后加速度 Ay</span>' + f[12].toFixed(2) + ' m/s²</div>' +
    '<div><span class="k">垂直加速度 Az</span>' + f[13].toFixed(2) + ' m/s²</div>';
}
function toggleTelRows() {
  const p = document.getElementById('tpanel'), b = document.getElementById('tp-fold');
  p.classList.toggle('folded');
  b.textContent = p.classList.contains('folded') ? '展开详细数据 ⌄' : '收起详细数据 ⌃';
  layoutPlayer();
}

/* ---------- 导出视频水印 (与遥测面板同款) ---------- */
function telFrameAt(t) {
  const fr = TEL.frames;
  let lo = 0, hi = fr.length - 1, ans = fr[0];
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (fr[mid][0] <= t) { ans = fr[mid]; lo = mid + 1; } else { hi = mid - 1; }
  }
  return ans;
}
function rrPath(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
function wmPill(ctx, xRight, yMid, text, bg, fg, s) {
  const fs = Math.round(12 * s);
  ctx.font = '700 ' + fs + 'px system-ui,"Segoe UI",sans-serif';
  const pw = ctx.measureText(text).width + Math.round(18 * s), ph = Math.round(24 * s);
  const x = xRight - pw;
  const sh = ctx.shadowBlur;
  ctx.shadowBlur = 0;               // 胶囊是实心色块, 不需要投影
  ctx.fillStyle = bg;
  rrPath(ctx, x, yMid - ph / 2, pw, ph, ph / 2); ctx.fill();
  ctx.shadowBlur = sh;
  ctx.fillStyle = fg;
  ctx.fillText(text, x + Math.round(9 * s), yMid + Math.round(fs * 0.36));
  return x;
}
function drawWm(ctx, t, W) {
  if (!TEL || !TEL.frames || !TEL.frames.length) return;
  const f = telFrameAt(t);
  const s = W / 1280, pad = Math.round(14 * s);
  const h = Math.round(46 * s), yc = h / 2;   // 单行窄条: 1280 宽时约 46px, 仅占画面高度 ~5%
  ctx.save();
  ctx.textBaseline = 'middle';
  // 极淡底 (15% 不透明): 只做一块轻微压暗, 天空/路面几乎不受影响
  ctx.shadowBlur = 0;
  ctx.fillStyle = 'rgba(13,18,26,.15)';
  ctx.fillRect(0, 0, W, h);
  // 文字加深色投影, 保证在明亮天空上也能看清
  ctx.shadowColor = 'rgba(0,0,0,.8)';
  ctx.shadowBlur = Math.round(5 * s);
  ctx.shadowOffsetY = Math.round(1.2 * s);
  // 左: 日期时间 + 城市/位置
  ctx.textAlign = 'left';
  ctx.font = '600 ' + Math.round(14 * s) + 'px system-ui,"Segoe UI",sans-serif';
  ctx.fillStyle = '#fff';
  const dateStr = telT0 ? fmtTelDate(new Date(telT0.getTime() + f[0] * 1000)) : '';
  ctx.fillText(dateStr, pad, yc + Math.round(1 * s));
  const dw = ctx.measureText(dateStr).width;
  const loc = [(TEL_META || {}).city, (TEL_META || {}).street].filter(Boolean).join(' · ');
  if (loc) {
    ctx.font = '500 ' + Math.round(13 * s) + 'px system-ui,"Segoe UI",sans-serif';
    ctx.fillStyle = '#eef3f8';
    ctx.fillText(loc, pad + dw + Math.round(10 * s), yc + Math.round(1 * s));
  }
  // 右侧自右向左: 油门 / 刹车 / 挡位 / 转向灯 / 车速
  let xr = W - pad;
  xr = wmPill(ctx, xr, yc, f[3] + '%', '#1f7ae0', '#fff', s) - Math.round(8 * s);
  xr = wmPill(ctx, xr, yc, '刹车',
    f[5] ? '#ff453a' : 'rgba(32,40,50,.5)', f[5] ? '#fff' : '#eef3f8', s) - Math.round(12 * s);
  // 挡位圆徽
  ctx.shadowBlur = 0;

  const gr = Math.round(13 * s);
  ctx.fillStyle = '#34c759';
  ctx.beginPath(); ctx.arc(xr - gr, yc, gr, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#fff'; ctx.textAlign = 'center';
  ctx.font = '800 ' + Math.round(14 * s) + 'px system-ui,"Segoe UI",sans-serif';
  ctx.fillText(f[1], xr - gr, yc + Math.round(1 * s));
  xr -= gr * 2 + Math.round(10 * s);
  // 转向灯三角 (右/左): 打灯是"一闪一闪", 不是常亮 (0.4s 一个节拍, 与导出视频里的水印同相位)
  const triS = Math.round(9 * s);
  const blinkOn = (Math.floor(t / 0.4) % 2) === 0;
  ctx.fillStyle = (f[6] === 2 && blinkOn) ? '#f59e0b' : '#4a545f';
  ctx.beginPath(); ctx.moveTo(xr - triS, yc - triS * 0.62); ctx.lineTo(xr - triS, yc + triS * 0.62); ctx.lineTo(xr, yc); ctx.closePath(); ctx.fill();
  xr -= triS + Math.round(7 * s);
  ctx.fillStyle = (f[6] === 1 && blinkOn) ? '#f59e0b' : '#4a545f';
  ctx.beginPath(); ctx.moveTo(xr, yc - triS * 0.62); ctx.lineTo(xr, yc + triS * 0.62); ctx.lineTo(xr - triS, yc); ctx.closePath(); ctx.fill();
  xr -= triS + Math.round(12 * s);
  // 车速 (先画右侧单位, 再画数字, 保证 "数字 km/h" 顺序)
  ctx.shadowBlur = Math.round(4 * s);   // 文字恢复投影
  ctx.textAlign = 'right';
  ctx.font = '500 ' + Math.round(11 * s) + 'px system-ui,"Segoe UI",sans-serif';
  ctx.fillStyle = '#eef3f8';
  ctx.fillText('km/h', xr, yc + Math.round(1 * s));
  xr -= ctx.measureText('km/h').width + Math.round(6 * s);
  ctx.font = '800 ' + Math.round(22 * s) + 'px system-ui,"Segoe UI",sans-serif';
  ctx.fillStyle = '#fff';
  const sp = String(Math.max(0, Math.round(f[2])));
  ctx.fillText(sp, xr, yc + Math.round(1 * s));
  // AP 方向盘徽标: 开了辅助驾驶 = 橙红实心圆 + 白色方向盘, 没开 = 深灰半透明圆 + 灰色方向盘
  // (以前没开就直接不画, 看起来像"没有这个图标"; 现在常显, 只区分状态)
  xr -= ctx.measureText(sp).width + Math.round(9 * s);
  const apv = f[7] | 0;
  wmApWheel(ctx, xr, yc, s, apv !== 0);
  ctx.restore();
}
function wmApWheel(ctx, xRight, yMid, s, on) {
  // 圆形徽标 + 方向盘图形 (与遥测面板里的方向盘图标同款): 圆环 + 横辐 + 竖辐 + 中心毂
  const R = Math.round(11 * s), cx = xRight - R, cy = yMid;
  const sh = ctx.shadowBlur;
  ctx.shadowBlur = 0;                       // 实心色块, 不要投影
  if (on) {
    // 启动: 蓝色渐变 (与车机上 AP 图标同色), 不再是橙红
    const g = ctx.createLinearGradient(cx - R, cy - R, cx + R, cy + R);
    g.addColorStop(0, '#2f7cf6'); g.addColorStop(1, '#1d5fd0');
    ctx.fillStyle = g;
  } else {
    ctx.fillStyle = 'rgba(38,46,56,.62)';   // 未启动: 中性灰底, 图标可见但明显灰掉
  }
  ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
  const ir = R * 0.60, lw = Math.max(1.2 * s, R * 0.13);
  const col = on ? '#fff' : '#c3ccd6';
  ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = lw;
  ctx.beginPath(); ctx.arc(cx, cy, ir, 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(cx - ir, cy); ctx.lineTo(cx + ir, cy);
  ctx.moveTo(cx, cy); ctx.lineTo(cx, cy + ir);
  ctx.stroke();
  ctx.beginPath(); ctx.arc(cx, cy, R * 0.16, 0, Math.PI * 2); ctx.fill();
  ctx.shadowBlur = sh;
  return cx - R - Math.round(8 * s);
}
function updateHud(t) {
  if (!TEL || !TEL.frames || !TEL.frames.length) return;
  const fr = TEL.frames;
  let lo = 0, hi = fr.length - 1, ans = fr[0];
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (fr[mid][0] <= t) { ans = fr[mid]; lo = mid + 1; } else { hi = mid - 1; }
  }
  renderHud(ans);
}
window.addEventListener('resize', () => { if (document.getElementById('player').classList.contains('open')) layoutPlayer(); });

/* ---------- 准实时预览 ---------- */
/* 画面框跟片源尺寸匹配 (与哨兵/记录仪播放器同一套思路):
   单路按 videoWidth/Height 定宽高, 最高 58vh 并居中; 全览按第一路比例算
   像素行高。Tesla 片源多为 4:3, 固定 16/9 + cover 会把上下裁掉一截。 */
function layoutLive() {
  const v = document.getElementById('lv-video');
  if (!v || !v.videoWidth || !v.videoHeight || v.style.display === 'none') return;
  const ar = v.videoWidth / v.videoHeight;
  const boxW = (v.parentElement && v.parentElement.clientWidth) || window.innerWidth;
  const w = Math.max(1, Math.min(boxW, window.innerHeight * 0.58 * ar));
  v.style.width = Math.round(w) + 'px';
  v.style.height = Math.round(w / ar) + 'px';
}
function layoutLiveGrid() {
  const g = document.getElementById('lv-grid');
  if (!g || !g.classList.contains('on')) return;
  const v0 = g.querySelector('video');
  if (!v0 || !v0.videoWidth || !v0.videoHeight) return;
  const cols = (g.children.length === 1 || g.classList.contains('n1')) ? 1 : 2;
  const w = g.clientWidth || 0;
  if (!w) return;
  const cw = (w - 3 * (cols - 1)) / cols;
  g.style.gridAutoRows = Math.round(cw * v0.videoHeight / v0.videoWidth) + 'px';
  g.classList.add('ready');
}
window.addEventListener('resize', () => { layoutLive(); layoutLiveGrid(); });
const _lvSingle = document.getElementById('lv-video');
if (_lvSingle) _lvSingle.addEventListener('loadedmetadata', layoutLive);

let liveCam = localStorage.getItem('tsflivecam') || 'front';
/* 画质: 与回放共用本地/远程默认档位, 并按网络类型分别记住手动选择 */
const LIVE_Q_STORE_KEY = 'tsfliveq-' + Q_NET_MODE;
let liveQ = localStorage.getItem(LIVE_Q_STORE_KEY) || '';
let liveFolder = '', liveTimer = null, liveBusy = false, liveLoading = false, liveSyncTimer = null, liveEv = null;
function liveQv() { return liveQ || curQ || 'orig'; }
function lvUrl(u) {
  const q = liveQv();
  if (q === 'orig') return u;
  return u + (u.indexOf('?') < 0 ? '?' : '&') + 'q=' + q;
}
function setLiveQ(v) {
  liveQ = v;
  localStorage.setItem(LIVE_Q_STORE_KEY, v);
  if (liveEv) renderLive(liveEv);
}
function latestLiveEv() { const arr = (data && data.RecentClips) || []; return arr[0] || null; }
function openLive() {
  document.getElementById('livep').classList.add('open');
  document.body.classList.add('livemode');       /* 隐藏分类/日期筛选与归档列表 */
  const qs = document.getElementById('lv-q');
  if (qs) qs.value = liveQv();
  /* 从播放器切过来时把播放器收起, 免得浮层盖在实时预览上 */
  if (document.getElementById('player').classList.contains('open')) closePlayer();
  const ev = latestLiveEv();
  if (ev) { liveFolder = ev.name; renderLive(ev); }
  try { window.scrollTo({ top: 0, behavior: 'smooth' }); } catch (e) { window.scrollTo(0, 0); }
  liveTick();
  liveRestart();
}
function closeLive() {
  document.getElementById('livep').classList.remove('open');
  document.body.classList.remove('livemode');
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  clearLiveGrid();
  const v = document.getElementById('lv-video');
  try { v.pause(); v.removeAttribute('src'); v.load(); } catch (err) {}
  /* 从实时预览返回时, 高亮恢复到当前分类页签 (不是固定第一个) */
  const tl = document.getElementById('tab-live');
  if (tl && tl.classList.contains('active')) {
    tl.classList.remove('active');
    const all = document.querySelectorAll('#tabs .tab');
    const ix = Object.keys(data || {}).indexOf(currentCat);
    const target = all[ix >= 0 ? ix : 0];
    if (target && target !== tl) target.classList.add('active');
  }
}
function renderLive(ev) {
  liveEv = ev;
  document.getElementById('lv-name').textContent = '最新片段: ' + ev.name.replace(/_/g, ' ');
  const vids = camSort(ev.videos || []);
  if (!vids.length) return;
  if (liveCam !== '__all' && !vids.find(v => v.cam === liveCam)) liveCam = '__all';
  const row = document.getElementById('lv-cams');
  row.innerHTML = '';
  const mkBtn = (cam, label) => {
    const b = document.createElement('button');
    b.className = 'lvbtn' + (cam === liveCam ? ' on' : '');
    b.textContent = label;
    b.onclick = () => { liveCam = cam; localStorage.setItem('tsflivecam', liveCam); renderLive(ev); };
    row.appendChild(b);
  };
  vids.forEach(v => mkBtn(v.cam, camLabel(v.cam)));
  /* 最后一个: 全览 (所有摄像头同屏) */
  mkBtn('__all', '全览 (' + vids.length + ')');
  const vid = document.getElementById('lv-video');
  const grid = document.getElementById('lv-grid');
  if (liveCam === '__all') {
    vid.style.display = 'none';
    try { vid.pause(); vid.removeAttribute('src'); vid.load(); } catch (err) {}
    buildLiveGrid(vids);
  } else {
    clearLiveGrid();
    vid.style.display = '';
    const v = vids.find(x => x.cam === liveCam) || vids[0];
    const want = lvUrl(v.url);
    if (v && vid.getAttribute('src') !== want) { vid.src = want; vid.play().catch(() => {}); }
    layoutLive();
  }
}
/* 全览: 每路一个 video, 同屏播放并互相对齐进度 */
function clearLiveGrid() {
  if (liveSyncTimer) { clearInterval(liveSyncTimer); liveSyncTimer = null; }
  const g = document.getElementById('lv-grid');
  g.classList.remove('on', 'n1', 'ready');
  g.style.gridAutoRows = '';
  [...g.querySelectorAll('video')].forEach(v => { try { v.pause(); v.removeAttribute('src'); v.load(); } catch (e) {} });
  g.innerHTML = '';
}
function buildLiveGrid(vids) {
  const g = document.getElementById('lv-grid');
  [...g.querySelectorAll('video')].forEach(v => { try { v.pause(); v.removeAttribute('src'); } catch (e) {} });
  g.innerHTML = '';
  g.classList.add('on');
  g.classList.toggle('n1', vids.length === 1);
  vids.forEach((v, ix) => {
    const cell = document.createElement('div');
    cell.className = 'lvcell';
    const el = document.createElement('video');
    el.playsInline = true; el.muted = true; el.preload = 'auto';
    el.onloadedmetadata = () => { el.currentTime = 0.05; el.play().catch(() => {}); };
    el.addEventListener('loadedmetadata', layoutLiveGrid);
    const lb = document.createElement('div');
    lb.className = 'clabel';
    lb.textContent = camLabel(v.cam);
    cell.appendChild(el); cell.appendChild(lb);
    cell.onclick = () => { liveCam = v.cam; localStorage.setItem('tsflivecam', liveCam); if (liveEv) renderLive(liveEv); };
    g.appendChild(cell);
    /* 逐路上屏: 每路错开 350ms, 避免 4 路同时抢占上行 */
    el.oncanplay = null;
    setTimeout(() => { if (!el.getAttribute('src')) el.src = lvUrl(v.url); }, ix * 350);
  });
  /* 每秒对齐一次进度, 任一路拖进度条/暂停 → 其余跟随 */
  if (liveSyncTimer) clearInterval(liveSyncTimer);
  liveSyncTimer = setInterval(() => {
    const vs = [...g.querySelectorAll('video')];
    if (!vs.length) return;
    const lead = vs.find(v => !v.paused && !v.seeking) || vs[0];
    vs.forEach(v => {
      if (v === lead) return;
      if (Math.abs((v.currentTime || 0) - (lead.currentTime || 0)) > 0.45) v.currentTime = lead.currentTime;
    });
  }, 1000);
}
async function liveTick() {
  if (liveBusy || !document.getElementById('livep').classList.contains('open')) return;
  liveBusy = true;
  const st = document.getElementById('lv-status');
  if (!st.textContent) st.textContent = '正在检查…';   /* 首次进入先给占位, 不让状态栏空白 */
  try {
    /* 网络抖动/上行被视频占满时响应可能为空或迟迟不回, 6 秒超时后放行, 下轮再试 */
    const ctrl = new AbortController();
    const to = setTimeout(() => ctrl.abort(), 6000);
    let txt;
    try { txt = await fetch('/api/live/status', { signal: ctrl.signal }).then(x => x.text()); }
    finally { clearTimeout(to); }
    let r = null;
    try { r = JSON.parse(txt); } catch (e) {}
    if (!r) { st.textContent = '检查暂时不可达, 下轮重试…'; return; }
    /* 状态文字先更新: 下面的全量列表刷新可能很慢 (设备负载高时数秒), 不能让它挡住状态栏 */
    if (!r.folder) st.textContent = '归档里还没有行车片段';
    else {
      /* age = 入库时刻 - 当前时刻 (负数), -1 表示目录里还没有可读文件 */
      const ago = (typeof r.age === 'number' && r.age < -1) ? -r.age : 0;
      st.textContent = !ago ? '' : ago < 60 ? '刚刚入库'
        : ago < 3600 ? Math.round(ago / 60) + ' 分钟前入库'
        : Math.round(ago / 3600) + ' 小时前入库';
    }
    /* 列表刷新异步进行, 不阻塞轮询; 防止上一次还没完成又发起一次 */
    if (r.folder && r.folder !== liveFolder && !liveLoading) {
      liveFolder = r.folder;
      liveLoading = true;
      load().then(() => {
        const ev = latestLiveEv();
        if (ev && document.getElementById('livep').classList.contains('open')) renderLive(ev);
      }).catch(() => {}).finally(() => { liveLoading = false; });
    }
  } catch (e) { st.textContent = '检查暂时不可达, 下轮重试…'; }
  finally { liveBusy = false; }
}
function liveRestart() {
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  const iv = +document.getElementById('lv-iv').value;
  if (iv > 0) liveTimer = setInterval(liveTick, iv * 1000);
}

/* ---------- 导出 ---------- */
let expQ = 'orig';
function renderExpQ() {
  const curLabel = (Q_LIST.find(x => x[0] === expQ) || Q_LIST[0])[1];
  document.getElementById('expq').innerHTML =
    `<button class="qbtn ${expQ !== 'orig' ? 'on' : ''}" onclick="toggleExpQ(event)">${curLabel} ⌃</button>` +
    '<div class="qmenu">' + Q_LIST.map(([k, label]) =>
      `<button class="${k === expQ ? 'on' : ''}" onclick="expQ='${k}';renderExpQ();closeQ()">${label}</button>`).join('') + '</div>';
}
function toggleExpQ(e) {
  if (e) e.stopPropagation();
  document.getElementById('expq').classList.toggle('open');
}
function openExport() {
  if (!cur) return;
  const box = document.getElementById('expchks'); box.innerHTML = '';
  camSort(curVids()).forEach(v => {
    const lb = document.createElement('label'); lb.className = 'expitem';
    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.value = v.cam; cb.checked = true;
    lb.appendChild(cb);
    lb.appendChild(document.createTextNode(camLabel(v.cam) + ' (' + v.cam + ')'));
    box.appendChild(lb);
  });
  // 水印勾选: 默认勾上。没有遥测的片段(停车哨兵)也允许加, 只是水印里只有时间+地点
  const hasTel = !!(TEL && TEL.frames && TEL.frames.length);
  const wm = document.getElementById('expwm'), wmRow = document.getElementById('expwm-row');
  wm.disabled = false;
  wm.checked = true;
  wmRow.style.opacity = '';
  wmRow.title = hasTel ? '' : '该片段没有行车遥测 (SEI), 水印只显示时间与地点';
  expQ = curQ;  // 默认跟随当前播放清晰度
  renderExpQ();
  checkFont();
  document.getElementById('expp').classList.add('open');
}
function closeExport() { document.getElementById('expp').classList.remove('open'); }
/* ---- 水印字体: 设备端烧 ASS 字幕必须有中文字体, 没有就烧不出水印 (以前是静默跳过) ---- */
let fontReady = null, fontInfo = null;
/* 字体状态: 页面加载时预热一次, 导出面板直接用缓存值 —— 播放器开着 4~6 路视频时
   浏览器对同域的 6 个连接会被视频占满, 面板里临时发的请求会一直排在"检查中" */
function paintFont() {
  const txt = document.getElementById('expfont-txt'), btns = document.getElementById('expfont-btns');
  if (!txt) return;
  if (fontReady === null) {
    txt.textContent = '水印字体: 状态未知 (不影响其它功能)';
    if (btns) btns.style.display = 'none';
    return;
  }
  if (fontReady) {
    txt.innerHTML = '<span style="color:#34c759">✓ 水印字体已就绪</span> ' +
      '<span style="color:#5b646d">' + ((fontInfo || {}).name || '') + ' · ' +
      (Math.round(((fontInfo || {}).size || 0) / 1048576 * 10) / 10) + 'MB</span>';
    if (btns) btns.style.display = 'none';
  } else {
    txt.innerHTML = '<span style="color:#ff453a">✕ 缺少中文字体, 水印烧不进去</span><br>' +
      '<span style="color:#5b646d;font-size:11px">点「安装字体」自动下载 (约17MB), 也可上传本地 ttf/otf</span>';
    if (btns) btns.style.display = 'flex';
  }
}
function loadFontInfo(force) {
  if (!force && fontInfo !== null) return Promise.resolve(fontInfo);
  return new Promise(res => {
    let done = false;
    const fin = d => {
      if (done) return;
      done = true;
      fontInfo = d && typeof d === 'object' ? d : null;
      fontReady = fontInfo ? !!fontInfo.ok : null;
      res(fontInfo);
    };
    const tm = setTimeout(() => fin(null), 3000);   // 连接被视频占满时别一直卡住
    fetch('/api/font', { cache: 'no-store' }).then(r => r.json())
      .then(d => { clearTimeout(tm); fin(d); })
      .catch(() => { clearTimeout(tm); fin(null); });
  });
}
function checkFont() {
  paintFont();
  if (fontInfo === null) loadFontInfo().then(paintFont);
}
function installFont() {
  const b = document.getElementById('expfont-btn'), txt = document.getElementById('expfont-txt');
  const old = b.textContent;
  b.disabled = true; b.textContent = '下载中…';
  txt.innerHTML = '<span style="color:#ffb340">正在从镜像下载字体 (约17MB, 可能 1~3 分钟)…</span>';
  fetch('/api/font/dl', { method: 'POST' }).then(r => r.json()).then(d => {
    toast(d.msg || (d.ok ? '字体已安装' : '安装失败'));
  }).catch(() => toast('安装失败: 网络不通? 试试「上传」本地字体'))
    .finally(() => { b.disabled = false; b.textContent = old; loadFontInfo(true).then(paintFont); });
}
function uploadFont(inp) {
  const f = inp.files && inp.files[0];
  if (!f) return;
  const fd = new FormData(); fd.append('file', f);
  document.getElementById('expfont-txt').textContent = '正在上传字体…';
  fetch('/api/font/upload', { method: 'POST', body: fd }).then(r => r.json()).then(d => {
    toast(d.msg || (d.ok ? '字体已安装' : '上传失败'));
  }).catch(() => toast('上传失败')).finally(() => { inp.value = ''; loadFontInfo(true).then(paintFont); });
}
function expChk(on) { [...document.querySelectorAll('#expchks input')].forEach(c => c.checked = on); }
function doExport() {
  if (!cur) return;
  const sel = [...document.querySelectorAll('#expchks input:checked')].map(c => c.value);
  if (!sel.length) { toast('请至少选择一路'); return; }
  const wm = document.getElementById('expwm').checked;
  // 设备端烧水印必须有中文字体, 缺了就明确拦住 (别静默给一段没有水印的视频)
  if (wm && fontReady === false) {
    toast('设备缺少中文字体, 水印烧不进去: 请先点「安装字体」');
    return;
  }
  closeExport();
  if (sel.length === 1 && !wm) {
    const v = curVids().find(x => x.cam === sel[0]);
    if (v) location.href = '/dl?path=' + encodeURIComponent('/archive/' + v.url.replace(/^\/media\//, '')) + (expQ !== 'orig' ? '&q=' + expQ : '');
    return;
  }
  // 带水印/多路一律交给设备端 ffmpeg: 直接出标准 H.264 mp4,
  // 浏览器 canvas 合成只能出 webm (微信发不出去), iOS 上还会被截断
  startServerExport(sel, wm);
}
/* 设备端合成导出: 输出标准 H.264 mp4 (带 faststart), 微信/相册都能直接发 */
function startServerExport(sel, wm) {
  const parts = ((curVids()[0] || {}).url || '').replace(/^\/media\//, '').split('/');
  const cat = parts[0] || '', name = parts[1] || '';
  if (!name) { toast('取不到当前事件信息, 请刷新重试'); return; }
  /* 只导出用户当前正在看的这一分钟, 把真实文件名告诉设备端 */
  const files = curVids()
    .filter(v => sel.indexOf(v.cam) >= 0)
    .map(v => v.f || v.url.split('/').pop())
    .filter(Boolean);
  const st = document.getElementById('stitch');
  const fill = document.getElementById('stfill'), pct = document.getElementById('stpct'),
        hint = document.getElementById('sthint');
  fill.style.width = '0%'; pct.textContent = '0%';
  hint.textContent = '正在设备上合成 mp4 (约 1~3 分钟, 请保持页面打开)…';
  st.classList.add('open');
  fetch('/api/export/burn', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cat: cat, name: name, cams: sel, wm: !!wm, files: files,
                           q: ({ 'orig': 'orig', '720p': '720p', '480p': '480p', '360p': '360p' })[expQ] || '720p' })
  }).then(r => r.json()).then(d => {
    if (!d.ok) { stitchFail(d.error || '导出失败'); return; }
    pollExport(d.id);
  }).catch(e => stitchFail('导出失败: ' + e));
}
function pollExport(id) {
  fetch('/api/stitch/status?id=' + encodeURIComponent(id)).then(r => r.json()).then(d => {
    if (d.state === 'error') { stitchFail(d.err || '导出失败'); return; }
    const pct = d.pct || 0;
    document.getElementById('stfill').style.width = pct + '%';
    document.getElementById('stpct').textContent = pct + '%';
    if (d.state === 'done') {
      document.getElementById('sthint').textContent = '合成完成, 开始下载…';
      location.href = '/api/export/burn/dl?id=' + encodeURIComponent(id);
      setTimeout(() => document.getElementById('stitch').classList.remove('open'), 2500);
      return;
    }
    setTimeout(() => pollExport(id), 1000);
  }).catch(() => setTimeout(() => pollExport(id), 1500));
}
function doPushFeishu() {
  if (!cur) return;
  const sel = [...document.querySelectorAll('#expchks input:checked')].map(c => c.value);
  if (!sel.length) { toast('请至少选择一路'); return; }
  const telOk = !!(TEL && TEL.frames && TEL.frames.length);
  const wm = document.getElementById('expwm').checked && telOk;
  closeExport();
  const parts = ((curVids()[0] || {}).url || '').replace(/^\/media\//, '').split('/');
  const cat = parts[0] || '', name = parts[1] || '';
  if (!name) { toast('取不到当前事件信息, 请刷新重试'); return; }
  startLocalStitch(sel, document.getElementById('stitch'), wm, { cat: cat, name: name, q: expQ });
}
function uploadPushVideo(blob, push) {
  const fill = document.getElementById('stfill'), pct = document.getElementById('stpct'),
        hint = document.getElementById('sthint');
  fill.style.width = '60%'; pct.textContent = '';
  hint.textContent = '已上传到设备, 正在转码并推送飞书 (约1-3分钟, 请保持页面打开)…';
  fetch('/api/push/upload?cat=' + encodeURIComponent(push.cat) + '&name=' + encodeURIComponent(push.name) +
        '&q=' + encodeURIComponent(push.q),
        { method: 'POST', body: blob, headers: { 'Content-Type': blob.type || 'video/webm' } })
    .then(r => r.json()).then(d => {
      if (d.ok) {
        fill.style.width = '100%'; pct.textContent = '100%';
        hint.textContent = '✅ ' + d.msg;
        setTimeout(() => document.getElementById('stitch').classList.remove('open'), 6000);
      } else stitchFail(d.msg || d.error || '推送失败');
    })
    .catch(e => stitchFail('推送失败: ' + e));
}
/* 浏览器本机合成: 设备端 ffmpeg 多路 1080p 会触发内核重启, 改由电脑实时录制合成 */
let recBusy = false;
function startLocalStitch(sel, st, wm, push) {
  if (recBusy) { toast('已有合成在进行'); return; }
  const vids = camSort(curVids()).filter(v => sel.includes(v.cam));
  if (!vids.length) { toast('请至少选择一路'); return; }
  if (!window.MediaRecorder || !HTMLCanvasElement.prototype.captureStream) {
    toast('此浏览器不支持本机合成, 请使用打包下载'); return;
  }
  const fill = document.getElementById('stfill'), pct = document.getElementById('stpct'),
        hint = document.getElementById('sthint');
  fill.style.width = '0%'; pct.textContent = '0%';
  hint.textContent = '正在本机合成 ' + vids.length + ' 路画面 (实时录制, 约 1 分钟), 请保持页面前台';
  st.classList.add('open');
  recBusy = true;
  const n = vids.length;
  let cols, CW, CH;
  if (n === 1) { cols = 1; CW = 1280; CH = 960; }        // 单路保持 4:3 原比例
  else { cols = n <= 4 ? 2 : 3; CW = 640; CH = 360; }
  const canvas = document.createElement('canvas');
  canvas.width = cols * CW; canvas.height = Math.ceil(n / cols) * CH;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#000'; ctx.fillRect(0, 0, canvas.width, canvas.height);
  const els = vids.map(v => {
    const el = document.createElement('video');
    el.muted = true; el.defaultMuted = true; el.preload = 'auto';
    el.setAttribute('muted', ''); el.setAttribute('playsinline', '');
    el.setAttribute('webkit-playsinline', ''); el.setAttribute('x5-playsinline', '');
    el.src = v.url;
    return el;
  });
  const cleanup = () => {
    els.forEach(e => { try { e.pause(); e.removeAttribute('src'); e.load(); } catch (err) {} });
    recBusy = false;
  };
  Promise.all(els.map(el => new Promise(res => {
    if (el.readyState >= 2) return res();
    el.addEventListener('loadeddata', res, { once: true });
    el.addEventListener('error', () => { toast('有画面加载失败, 请重试'); res(); }, { once: true });
    setTimeout(res, 30000);
  }))).then(() => {
    let mime = '';
    // 优先录 mp4 (微信/相册直接可发), 浏览器不支持再退 webm
    for (const m of ['video/mp4;codecs=avc1.42E01E', 'video/mp4',
                     'video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm']) {
      if (MediaRecorder.isTypeSupported(m)) { mime = m; break; }
    }
    if (!mime) { cleanup(); st.classList.remove('open'); toast('此浏览器不支持本机合成'); return; }
    const ext = mime.indexOf('mp4') >= 0 ? 'mp4' : 'webm';
    const dur = Math.max(1, ...els.map(e => isFinite(e.duration) ? e.duration : 0));
    const chunks = [];
    const rec = new MediaRecorder(canvas.captureStream(30), { mimeType: mime, videoBitsPerSecond: 5000000 });
    rec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onerror = () => { cleanup(); st.classList.remove('open'); toast('录制失败, 请重试'); };
    rec.onstop = () => {
      cleanup();
      const blob = new Blob(chunks, { type: mime.split(';')[0] });
      if (push) { uploadPushVideo(blob, push); return; }
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = (cur ? cur.name : 'teslacam') + '_' + sel.length + '路.' + ext;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 30000);
      hint.textContent = t('合成完成') + ', ' + t('已开始下载');
      pct.textContent = '100%'; fill.style.width = '100%';
      setTimeout(() => st.classList.remove('open'), 2500);
    };
    els.forEach(e => { try { e.currentTime = 0; e.play().catch(() => {}); } catch (err) {} });
    rec.start(1000);
    const t0 = performance.now();
    (function draw() {
      const t = (performance.now() - t0) / 1000;
      els.forEach((e, i) => {
        try { ctx.drawImage(e, (i % cols) * CW, Math.floor(i / cols) * CH, CW, CH); } catch (err) {}
      });
      if (wm) drawWm(ctx, t, canvas.width);
      const p = Math.min(99, Math.round(t / dur * 100));
      fill.style.width = p + '%'; pct.textContent = p + '%';
      const allDone = els.every(e => e.ended || (isFinite(e.duration) && e.currentTime >= e.duration - 0.05));
      if (t >= dur + 0.8 || allDone) { try { rec.stop(); } catch (err) {} return; }
      requestAnimationFrame(draw);
    })();
  });
}
function pollStitch(id) {
  fetch('/api/stitch/status?id=' + encodeURIComponent(id)).then(r => r.json()).then(d => {
    if (d.state === 'error') { stitchFail(d.err || t('合成失败')); return; }
    const pct = d.pct || 0;
    document.getElementById('stfill').style.width = pct + '%';
    document.getElementById('stpct').textContent = pct + '%';
    if (d.state === 'done') {
      document.getElementById('sthint').textContent = '合成完成, 开始下载…';
      location.href = '/api/stitch/dl?id=' + encodeURIComponent(id);
      setTimeout(() => document.getElementById('stitch').classList.remove('open'), 2500);
      return;
    }
    setTimeout(() => pollStitch(id), 800);
  }).catch(() => setTimeout(() => pollStitch(id), 1500));
}
function stitchFail(msg) {
  document.getElementById('sthint').textContent = t('合成失败') + ': ' + msg;
  document.getElementById('stpct').textContent = '';
  setTimeout(() => document.getElementById('stitch').classList.remove('open'), 5000);
}
function doExportZip() {
  if (!cur) return;
  const sel = [...document.querySelectorAll('#expchks input:checked')].map(c => c.value);
  if (!sel.length) { toast('请至少选择一路'); return; }
  closeExport();
  location.href = '/api/export/' + encodeURIComponent(currentCat) + '/' + encodeURIComponent(cur.name) + '?cams=' + encodeURIComponent(sel.join(',')) + (expQ !== 'orig' ? '&q=' + expQ : '');
}
document.getElementById('startmask').addEventListener('click', playAll);
function tryPlay(v) { const p = v.play(); if (p && p.catch) p.catch(() => {}); }
function playAll() {
  const vs = [...document.querySelectorAll('#vgrid video')];
  // iOS/微信只允许在用户手势里逐个调 play(); 同步循环内依次触发
  vs.forEach(tryPlay);
  const m = document.getElementById('startmask');
  if (m) m.classList.remove('show');
  const pp = document.getElementById('ppbtn'); if (pp) pp.textContent = '⏸';
}
function pauseAll() {
  document.querySelectorAll('#vgrid video').forEach(v => v.pause());
  const pp = document.getElementById('ppbtn'); if (pp) pp.textContent = '▶';
}
let baseRate = 1;
/* 单格自救: 四格同播时偶尔有一格的连接在 frp 隧道里卡死 (readyState 长期为 1/0,
   其余几格正常播放)。7 秒还拿不到数据就给这一格重发请求 —— 浏览器会换一条新连接,
   卡死的旧连接由服务端的断开感知回收。每格每次渲染最多自救一次, 防止死循环。 */
function kickStalled() {
  const vs = [...document.querySelectorAll('#vgrid video')];
  if (vs.length < 2) return;
  if (!vs.some(v => v.readyState >= 3 && !v.paused)) {
    vs.forEach(v => { v._st = 0; });      // 全体都没在播 (刚打开/暂停), 不算卡死
    return;
  }
  const now = Date.now();
  vs.forEach(v => {
    if (v.readyState >= 2 || v.ended) { v._st = 0; return; }
    if (!v._st) { v._st = now; return; }
    if (now - v._st > 7000 && !v._re) {
      v._re = 1;
      const ct = vs[0].currentTime || v.currentTime || 0;
      v.src = v.src;
      v.addEventListener('loadedmetadata', () => {
        try { if (ct) v.currentTime = Math.min(ct, Math.max(0, (v.duration || 0) - 0.4)); } catch (e) {}
        tryPlay(v);
      }, { once: true });
      tryPlay(v);
    }
  });
}
function setSpeed(s) {
  const r = parseFloat(s);
  baseRate = r;
  document.querySelectorAll('#vgrid video').forEach(v => v.playbackRate = r);
  const b = document.getElementById('spdbtn'); if (b) b.textContent = r + 'x';
}
const SPEEDS = [0.5, 1, 2, 4];
function cycleSpeed() {
  const now = parseFloat(document.getElementById('spdbtn').textContent) || 1;
  setSpeed(SPEEDS[(SPEEDS.indexOf(now) + 1) % SPEEDS.length]);
}
function togglePlay() {
  const vs = [...document.querySelectorAll('#vgrid video')];
  if (!vs.length) return;
  if (vs.some(v => v.paused)) playAll(); else pauseAll();
}
function switchPreviewVideos(target) {
  const vs = [...document.querySelectorAll('#vgrid video')];
  vs.forEach(v => {
    if (!v._preview) return;
    v._preview = false;
    const ct = (target != null) ? target : (v.currentTime || 0);
    v.src = v._fullUrl;
    v.addEventListener('loadedmetadata', () => {
      try { v.currentTime = Math.min(ct, Math.max(0, (v.duration || 0) - 0.2)); } catch (e) {}
      tryPlay(v);
    }, { once: true });
  });
}
function tick() {
  kickStalled();
  const vs = [...document.querySelectorAll('#vgrid video')];
  if (!vs.length || !vs[0].duration) return;
  const t = vs[0].currentTime;
  if (t >= 9 && vs.some(v => v._preview)) switchPreviewVideos(t);
  vs.forEach((v, i) => {
    if (i && v.paused && !vs[0].paused && !v.ended) {
      if (v.readyState >= 2) tryPlay(v);   // 还在缓冲(waiting)的视频不要反复强拉, 会卡
      return;
    }
    if (vs[0].paused || v.paused || v.ended) return;
    const d = v.currentTime - t;
    if (Math.abs(d) > 1.2) { v.currentTime = t; }              // 大漂移才硬seek
    else if (Math.abs(d) > 0.05) {                             // 小漂移: 微调倍速平滑收敛, 不跳帧不抽搐
      const m = Math.min(1.12, Math.max(0.88, 1 - d / 2));
      v.playbackRate = baseRate * m;
    } else if (v.playbackRate !== baseRate) {
      v.playbackRate = baseRate;
    }
  });
  document.getElementById('seek').value = Math.round(t / vs[0].duration * 1000);
  document.getElementById('ptime').textContent = fmtSec(t);
  document.getElementById('ic-dur').textContent = fmtSec(vs[0].duration);
  updateHud(t);
}
function fmtSec(x) {
  x = Math.max(0, Math.floor(x || 0));
  return String(Math.floor(x / 60)).padStart(2, '0') + ':' + String(x % 60).padStart(2, '0');
}
let scrubT = 0;
function applySeekAll(frac) {
  const vs = [...document.querySelectorAll('#vgrid video')];
  if (!vs.length || !vs[0].duration) return;
  const tt = frac / 1000 * vs[0].duration;
  if (tt >= 9 && vs.some(v => v._preview)) { switchPreviewVideos(tt); return; }
  vs.forEach(v => { try { v.currentTime = tt; } catch (e) {} });
}
document.getElementById('seek').oninput = function () {
  const now = Date.now();
  if (now - scrubT < 250) return;   // 拖动时节流, 避免 4-6 路同时连发 seek 卡顿
  scrubT = now;
  applySeekAll(+this.value);
};
document.getElementById('seek').onchange = function () {
  scrubT = 0;
  applySeekAll(+this.value);   // 松手必须对齐全部, 否则节流会吞掉最后位置
};
function closePlayer() {
  pauseAll();
  stopPlaybackSession();
  if (syncTimer) clearInterval(syncTimer);
  [...document.querySelectorAll('#vgrid video')].forEach(v => {
    try { v.removeAttribute('src'); v.load(); } catch (e) {}
  });
  [...document.querySelectorAll('#vgrid .vcell')].forEach(c => { c.classList.remove('focused'); c.style.display = ''; });
  document.getElementById('player').classList.remove('open');
}
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  const f = document.querySelector('#vgrid .vcell.focused');
  if (f) { focusCell(f); return; }
  closeExport(); closePlayer(); closePanel();
});

/* ---------- 设置面板 ---------- */
function toast(msg) {
  const box = document.getElementById('toast');
  box.textContent = t(msg); box.style.display = 'block';
  setTimeout(() => box.style.display = 'none', 2500);
}
function doLogout() {
  if (!confirm(t('确定要退出登录吗？'))) return;
  location.href = '/logout';
}
function stab(which) {
  ['net', 'files', 'audio', 'wraps', 'notify', 'auth', 'lang', 'skin', 'fan', 'brand', 'update'].forEach(k => {
    const b = document.getElementById('st-' + k), t = document.getElementById('tab-' + k);
    if (b) b.classList.toggle('active', k === which);
    if (t) t.style.display = k === which ? '' : 'none';
  });
  if (fanTimer) { clearInterval(fanTimer); fanTimer = null; }
  if (netTimer) { clearInterval(netTimer); netTimer = null; }
  if (which === 'fan') { fanLoad(); fanTimer = setInterval(fanTick, 5000); }
  if (which === 'net') { netLoad(); netTimer = setInterval(netTick, 5000); }
  if (which === 'update') { otaCheck(false); autoLoad(); }
  if (which === 'notify') ntLoad();
  if (which === 'auth') pwLoad();
  if (which === 'wraps') refreshWraps();
  if (which === 'brand') refreshBrand();
  if (which === 'skin') applyStyle(localStorage.getItem(STYLE_KEY) || 'default');
}

/* ---------- 风扇设置 ---------- */
let fanTimer = null;
function fanModeChange() {
  const manual = document.getElementById('fan-mode').value === 'manual';
  document.getElementById('fan-manual-row').style.opacity = manual ? '1' : '.45';
}
function fanLive(j) {
  const tp = (j.temp == null) ? '--' : j.temp.toFixed(1) + '°C';
  const du = (j.duty == null) ? '--' : j.duty + '%';
  document.getElementById('fan-live').textContent = t('当前温度') + ' ' + tp + ' · ' + t('当前占空比') + ' ' + du;
}
function fanErr(msg) {
  const e = document.getElementById('fan-err');
  if (msg) { e.textContent = t(msg); e.style.display = ''; }
  else e.style.display = 'none';
}
async function fanLoad() {
  try {
    const j = await (await fetch('/api/fan')).json();
    document.getElementById('fan-mode').value = j.mode || 'auto';
    const d = (j.manual == null) ? 50 : j.manual;
    document.getElementById('fan-duty').value = d;
    document.getElementById('fan-duty-text').textContent = d + '%';
    fanModeChange();
    fanLive(j);
    fanErr(j.present ? '' : '风扇不可用: 未启用 overlay 或温控服务未运行');
  } catch (e) {
    fanErr('读取风扇状态失败');
  }
}
async function fanTick() {
  try { fanLive(await (await fetch('/api/fan')).json()); } catch (e) {}
}
async function fanSave() {
  const mode = document.getElementById('fan-mode').value;
  const manual = +document.getElementById('fan-duty').value;
  try {
    const r = await fetch('/api/fan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode, manual }) });
    const j = await r.json();
    if (j.ok) { fanErr(''); fanLoad(); }
    else fanErr(j.msg || '保存失败');
  } catch (e) {
    fanErr('保存失败');
  }
}

/* ---------- 网络设置 ---------- */
let netTimer = null;
function netWMode() {
  document.getElementById('net-static').style.display =
    document.getElementById('net-wmode').value === 'static' ? '' : 'none';
}
function netErr(msg) {
  const e = document.getElementById('net-err');
  if (msg) { e.textContent = t(msg); e.style.display = ''; }
  else e.style.display = 'none';
}
function netLive(j) {
  const w = j.wired || {}, wi = j.wifi || {};
  document.getElementById('net-wired-live').textContent =
    (w.iface || 'end0') + ' · ' + (w.link || '--') + ' · IP ' + ((w.ipv4 || []).join(', ') || '--') +
    ' · GW ' + (w.gw || '--') + ' · DNS ' + ((w.dns || []).join(', ') || '--');
  document.getElementById('net-wifi-live').textContent = wi.present
    ? ((wi.ssid || '--') + ' · ' + (wi.link || '--') + ' · IP ' + ((wi.ipv4 || []).join(', ') || '--'))
    : t('未检测到无线网卡');
  const ap = j.ap || {}, bt = j.bt || {};
  document.getElementById('net-ap-live').textContent =
    t(ap.mode === 'auto' ? '自动' : (ap.mode === '1' ? '开启' : '关闭')) + ' · ' + (ap.ssid || '--') + ' · ch' + (ap.channel || '-') +
    '(' + (ap.hw_mode || '-') + ') · ' + (ap.up ? 'UP' : 'DOWN') + ' · ' + t('客户端') + ' ' + (ap.clients || 0);
  document.getElementById('net-bt-live').textContent = bt.present
    ? (t('蓝牙') + ' ' + (bt.powered ? t('开启') : t('关闭')) + ' · ' +
       (bt.discoverable ? t('可被发现') : t('不可被发现')) + ' · ' + (bt.name || '--'))
    : t('未检测到蓝牙');
  const roll = document.getElementById('net-roll'), row = document.getElementById('net-roll-row');
  if (j.roll_pending) {
    roll.textContent = t('网络已应用: 90 秒内确认连接, 否则自动回滚');
    roll.style.display = ''; row.style.display = '';
  } else { roll.style.display = 'none'; row.style.display = 'none'; }
}
async function netLoad() {
  try {
    const j = await (await fetch('/api/net')).json();
    const w = j.wired || {};
    document.getElementById('net-wmode').value = w.dhcp ? 'dhcp' : 'static';
    document.getElementById('net-ip').value = w.cfg_ip || '';
    document.getElementById('net-prefix').value = w.cfg_prefix || '24';
    document.getElementById('net-gw').value = w.cfg_gw || '';
    document.getElementById('net-dns').value = (w.cfg_dns || []).join(', ');
    const ap = j.ap || {}, bt = j.bt || {};
    document.getElementById('net-ap-enable').value = ap.mode || '0';
    document.getElementById('net-ap-ssid').value = ap.ssid || '';
    document.getElementById('net-ap-psk').value = ap.psk || '';
    document.getElementById('net-ap-band').value = ap.band || 'auto';
    document.getElementById('net-ap-chmode').value = ap.ch_mode || 'auto';
    document.getElementById('net-ap-ch').value = ap.ch_manual || '';
    netApChMode();
    document.getElementById('net-bt-power').value = bt.powered ? '1' : '0';
    document.getElementById('net-bt-disc').value = bt.discoverable ? '1' : '0';
    document.getElementById('net-bt-name').value = bt.name || '';
    netBtRender(bt.devices || []);
    netWMode();
    netLive(j);
    netErr('');
  } catch (e) {
    netErr('应用失败');
  }
}
async function netTick() {
  try { netLive(await (await fetch('/api/net')).json()); } catch (e) {}
}
async function netPost(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  return r.json();
}
async function netApplyWired() {
  const mode = document.getElementById('net-wmode').value;
  const body = {
    mode,
    ip: document.getElementById('net-ip').value.trim(),
    prefix: document.getElementById('net-prefix').value.trim(),
    gw: document.getElementById('net-gw').value.trim(),
    dns: document.getElementById('net-dns').value.split(',').map(s => s.trim()).filter(Boolean)
  };
  try {
    const j = await netPost('/api/net/wired', body);
    if (j.ok) { netErr(''); netLoad(); } else netErr(j.msg || '应用失败');
  } catch (e) { netErr('应用失败'); }
}
async function netApplyWifi() {
  const body = { ssid: document.getElementById('net-ssid').value.trim(), psk: document.getElementById('net-psk').value };
  try {
    const j = await netPost('/api/net/wifi', body);
    if (j.ok) { netErr(''); netLoad(); } else netErr(j.msg || '应用失败');
  } catch (e) { netErr('应用失败'); }
}
async function netForget() {
  try {
    const j = await netPost('/api/net/wifi/forget', {});
    if (j.ok) { netErr(''); netLoad(); } else netErr(j.msg || '应用失败');
  } catch (e) { netErr('应用失败'); }
}
async function netConfirm() {
  try {
    const j = await netPost('/api/net/confirm', {});
    netErr(j.msg || '');
    netLoad();
  } catch (e) { netErr('应用失败'); }
}
async function netScan() {
  const box = document.getElementById('net-aps');
  box.textContent = t('扫描中…');
  try {
    const j = await netPost('/api/net/wifi/scan', {});
    box.textContent = '';
    if (!j.ok) { netErr(j.msg || '应用失败'); return; }
    netErr('');
    (j.aps || []).forEach(a => {
      const b = document.createElement('button');
      b.className = 'storage-btn';
      b.textContent = a.ssid + ' (' + a.signal + ' dBm, ' + t(a.sec) + ')';
      b.onclick = () => {
        document.getElementById('net-ssid').value = a.ssid;
        document.getElementById('net-psk').focus();
      };
      box.appendChild(b);
    });
    if (!(j.aps || []).length) box.textContent = '--';
  } catch (e) {
    box.textContent = '';
    netErr('应用失败');
  }
}
function netApChMode() {
  document.getElementById('net-ap-ch').style.display =
    document.getElementById('net-ap-chmode').value === 'manual' ? '' : 'none';
}
async function netApplyAp() {
  const body = {
    enable: document.getElementById('net-ap-enable').value,
    ssid: document.getElementById('net-ap-ssid').value.trim(),
    psk: document.getElementById('net-ap-psk').value,
    band: document.getElementById('net-ap-band').value,
    channel_mode: document.getElementById('net-ap-chmode').value,
    channel: parseInt(document.getElementById('net-ap-ch').value, 10) || 0
  };
  try {
    const j = await netPost('/api/net/ap', body);
    if (j.ok) { netErr(''); netLoad(); } else netErr(j.msg || '应用失败');
  } catch (e) { netErr('应用失败'); }
}
async function netApplyBt() {
  const body = {
    power: document.getElementById('net-bt-power').value === '1',
    discoverable: document.getElementById('net-bt-disc').value === '1',
    name: document.getElementById('net-bt-name').value.trim()
  };
  try {
    const j = await netPost('/api/net/bt', body);
    if (j.ok) { netErr(''); netLoad(); } else netErr(j.msg || '应用失败');
  } catch (e) { netErr('应用失败'); }
}
function netBtRender(devs) {
  const box = document.getElementById('net-bt-devs');
  box.textContent = '';
  devs.forEach(d => {
    const b = document.createElement('button');
    b.className = 'storage-btn';
    b.textContent = d.name + (d.connected ? ' ✓' : '') + (d.paired ? ' (' + t('已配对') + ')' : '');
    b.title = d.mac;
    b.onclick = () => netBtAct(d.mac, d.paired);
    box.appendChild(b);
  });
}
async function netBtAct(mac, paired) {
  try {
    const j = await netPost(paired ? '/api/net/bt/remove' : '/api/net/bt/pair', { mac });
    if (!j.ok) netErr(j.msg || '应用失败'); else netErr('');
    netLoad();
  } catch (e) { netErr('应用失败'); }
}
async function netBtScan() {
  const box = document.getElementById('net-bt-devs');
  box.textContent = t('扫描中…');
  try {
    const j = await netPost('/api/net/bt/scan', {});
    if (!j.ok) { box.textContent = ''; netErr(j.msg || '应用失败'); return; }
    netErr('');
    netBtRender(j.devices || []);
    if (!(j.devices || []).length) box.textContent = '--';
  } catch (e) {
    box.textContent = '';
    netErr('应用失败');
  }
}

/* ---------- 飞书推送 ---------- */
const NT_SENS = ['nt-to', 'nt-appid', 'nt-hook', 'nt-url'];
let ntHidden = true;            // 默认隐藏, 截图安全
function ntMask(v) {
  v = (v || '').trim();
  if (!v) return '';
  if (v.length <= 8) return '•'.repeat(10);
  return v.slice(0, 4) + '•'.repeat(Math.min(20, v.length - 7)) + v.slice(-3);
}
function ntMaskUrl(v) {
  v = (v || '').trim();
  if (!v) return '';
  const m = /^([a-z]+:\/\/)/i.exec(v);
  return (m ? m[1] : '') + '•'.repeat(12);
}
function ntClearReal() {
  NT_SENS.forEach(id => { const el = document.getElementById(id); if (el) delete el.dataset.real; });
}
function ntReal(id) {
  const el = document.getElementById(id);
  if (!el) return '';
  return (el.dataset.real !== undefined ? el.dataset.real : el.value || '').trim();
}
function ntSetEye(hide) {
  ntHidden = !!hide;
  NT_SENS.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    if (ntHidden) {
      if (el.dataset.real === undefined) el.dataset.real = el.value || '';
      el.value = id === 'nt-url' ? ntMaskUrl(el.dataset.real) : ntMask(el.dataset.real);
      el.readOnly = true;
      el.classList.add('masked');
    } else {
      if (el.dataset.real !== undefined) { el.value = el.dataset.real; delete el.dataset.real; }
      el.readOnly = false;
      el.classList.remove('masked');
    }
  });
  const sec = document.getElementById('nt-secret');
  if (sec) sec.placeholder = ntHidden ? 'App Secret ••••••••••'
    : (sec.dataset.has === '1' ? 'App Secret 已保存, 留空表示不修改' : 'App Secret');
  const btn = document.getElementById('nt-eye'), tip = document.getElementById('nt-eyetip');
  if (btn) btn.innerHTML = '<svg class="ic"><use href="#' + (ntHidden ? 'i-eye' : 'i-eye-off') + '"/></svg>'
    + (ntHidden ? '显示' : '隐藏');
  if (tip) tip.textContent = ntHidden ? '敏感信息已隐藏（截图安全）' : '敏感信息已明文显示，注意别外发';
}
function ntToggleEye() { ntSetEye(!ntHidden); }

async function ntLoad() {
  try {
    const j = await (await fetch('/api/notify', { cache: 'no-store' })).json();
    document.getElementById('nt-en').checked = !!j.enabled;
    document.getElementById('nt-saved').checked = !!j.saved;
    document.getElementById('nt-mode').value = j.mode || 'dm';
    document.getElementById('nt-media').value = j.media || 'thumb';
    document.getElementById('nt-quality').value = j.quality || '480p';
    document.getElementById('nt-vdur').value = j.vdur || 30;
    ntMediaUI();
    ntClearReal();
    document.getElementById('nt-to').value = j.receive_id || '';
    document.getElementById('nt-hook').value = j.webhook || '';
    document.getElementById('nt-appid').value = j.app_id || '';
    document.getElementById('nt-secret').value = '';
    document.getElementById('nt-secret').dataset.has = j.has_secret ? '1' : '0';
    document.getElementById('nt-url').value = j.public_url || '';
    document.getElementById('nt-delay').value = j.delay || 20;
    ntSetEye(ntHidden);
    const m = document.getElementById('nt-msg');
    if (j.last && j.last.msg) {
      m.textContent = t('最近一次') + ': ' + (j.last.ok ? '✅ ' : '❌ ') + j.last.msg + ' (' + new Date(j.last.at * 1000).toLocaleString() + ')';
      m.style.color = j.last.ok ? '#4cc38a' : 'var(--accent)';
    } else if (!j.enabled) { m.textContent = t('未启用'); m.style.color = ''; }
    else if (j.dm_ready) { m.textContent = t('已启用私聊推送, 等下一个哨兵事件'); m.style.color = ''; }
    else { m.textContent = t('已启用, 但接收人/应用凭据未配全'); m.style.color = 'var(--accent)'; }
  } catch (e) { document.getElementById('nt-msg').textContent = t('读取设置失败') + ': ' + e; }
}
async function ntSave() {
  const body = {
    enabled: document.getElementById('nt-en').checked,
    saved: document.getElementById('nt-saved').checked,
    mode: document.getElementById('nt-mode').value,
    media: document.getElementById('nt-media').value,
    quality: document.getElementById('nt-quality').value,
    vdur: +document.getElementById('nt-vdur').value || 30,
    receive_id: ntReal('nt-to'),
    webhook: ntReal('nt-hook'),
    app_id: ntReal('nt-appid'),
    app_secret: document.getElementById('nt-secret').value.trim(),
    public_url: ntReal('nt-url'),
    delay: +document.getElementById('nt-delay').value || 20,
  };
  if (body.enabled) {
    const secSaved = document.getElementById('nt-secret').dataset.has === '1';
    const hasApp = body.app_id && (body.app_secret || secSaved);
    if (body.mode === 'dm' && (!hasApp || !body.receive_id)) { toast('私聊需要 App ID / Secret + 接收人'); return; }
    if (body.mode === 'group' && !body.webhook) { toast('请先填群机器人 webhook'); return; }
  }
  const m = document.getElementById('nt-msg');
  m.textContent = t('保存中…');
  try {
    const j = await (await fetch('/api/notify/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();
    m.textContent = (j.ok ? '✅ ' + t('已保存') : '❌ ' + j.msg) + (j.warn ? ' · ' + j.warn : '');
    m.style.color = j.ok ? '#4cc38a' : 'var(--accent)';
    if (j.ok) ntLoad();
  } catch (e) { m.textContent = t('保存失败') + ': ' + e; m.style.color = 'var(--accent)'; }
}
async function ntTest() {
  const m = document.getElementById('nt-msg');
  m.textContent = t('正在发送测试卡片…'); m.style.color = '';
  try {
    const j = await (await fetch('/api/notify/test', { method: 'POST' })).json();
    m.textContent = (j.ok ? '✅ ' : '❌ ') + j.msg;
    m.style.color = j.ok ? '#4cc38a' : 'var(--accent)';
  } catch (e) { m.textContent = t('发送失败') + ': ' + e; m.style.color = 'var(--accent)'; }
}

function ntMediaUI() {
  const v = document.getElementById('nt-media').value === 'video';
  document.getElementById('nt-vwrap').style.display = v ? '' : 'none';
}

/* ---------- 账号: 改登录密码 ---------- */
async function pwLoad() {
  try {
    const j = await (await fetch('/api/auth/info', { cache: 'no-store' })).json();
    document.getElementById('pw-user').textContent = j.user || 'admin';
    const m = document.getElementById('pw-msg');
    if (!j.on) { m.textContent = t('当前未开启登录保护, 设置密码后即开启'); m.style.color = 'var(--muted2)'; }
  } catch (e) {}
}
async function pwSave() {
  const m = document.getElementById('pw-msg');
  const o = document.getElementById('pw-old').value;
  const n = document.getElementById('pw-new').value;
  const n2 = document.getElementById('pw-new2').value;
  if (n.length < 6) { m.textContent = t('新密码至少 6 位'); m.style.color = 'var(--accent)'; return; }
  if (n !== n2) { m.textContent = t('两次输入的新密码不一致'); m.style.color = 'var(--accent)'; return; }
  m.textContent = t('提交中…'); m.style.color = '';
  try {
    const j = await (await fetch('/api/auth/pass', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old: o, 'new': n }) })).json();
    if (!j.ok) { m.textContent = '❌ ' + t(j.msg); m.style.color = 'var(--accent)'; return; }
    // 旧 cookie 已随 secret 更换失效, 用新密码立即重新登录, 保持本机不掉线
    try {
      await fetch('/login', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'u=' + encodeURIComponent(j.user || 'admin') + '&p=' + encodeURIComponent(n) });
    } catch (e) {}
    document.getElementById('pw-old').value = '';
    document.getElementById('pw-new').value = '';
    document.getElementById('pw-new2').value = '';
    m.textContent = '✅ ' + j.msg;
    m.style.color = '#4cc38a';
  } catch (e) { m.textContent = t('修改失败') + ': ' + e; m.style.color = 'var(--accent)'; }
}

/* ---------- 系统更新 (OTA) ---------- */
let otaInfo = null;
function esc(s) { return String(s == null ? '' : s).replace(/[<>&]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c])); }
async function otaCheck(force) {
  const tag = document.getElementById('upd-tag'), msg = document.getElementById('upd-msg');
  tag.className = 'updtag'; tag.textContent = t('检查中…');
  msg.textContent = t('正在连接 GitHub…');
  try {
    const j = await (await fetch('/api/ota/check' + (force ? '?force=1' : ''), { cache: 'no-store' })).json();
    otaInfo = j;
    document.getElementById('upd-cur').textContent = 'v' + j.current;
    document.getElementById('upd-new').textContent = j.latest ? 'v' + j.latest : '—';
    tag.className = 'updtag' + (j.has_update ? ' new' : '');
    tag.textContent = j.error ? t('检查失败') : (j.has_update ? t('有新版本') : t('已是最新'));
    const n = document.getElementById('upd-notes');
    if (j.notes && j.notes.length) {
      n.innerHTML = j.notes.map(x => '· ' + esc(x)).join('<br>');
      n.style.display = 'block';
    } else { n.style.display = 'none'; n.innerHTML = ''; }
    document.getElementById('upd-go').disabled = !j.has_update;
    document.getElementById('upd-rb').style.display = j.rollback_ready ? '' : 'none';
    renderAutoUpdate(j);
    msg.textContent = j.error
      ? t('连不上 GitHub') + ': ' + j.error + ' ' + t('(可稍后重试)')
      : (t('来源') + ': ' + (j.source || '-') + (j.date ? ' · ' + j.date : '') + (j.has_update ? '' : ' · ' + t('已是最新')));
    document.getElementById('gear').classList.toggle('hasupd', !!j.has_update);
  } catch (e) {
    tag.className = 'updtag'; tag.textContent = t('检查失败');
    msg.textContent = t('检查失败') + ': ' + e;
  }
}
/* 自动更新开关: 勾选即写入 settings.json (默认开启) */
function renderAutoUpdate(j) {
  const cb = document.getElementById('upd-auto'), el = document.getElementById('upd-autohint');
  if (!cb || !el) return;
  cb.checked = !!j.auto;
  let s = j.auto
    ? '已开启: 每 5 分钟检查一次, 发现新版本且没人看视频时自动升级'
    : '已关闭: 只用下方按钮手动升级';
  if (j.auto) {
    const when = j.auto_checked ? new Date(j.auto_checked * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '';
    if (when || j.auto_msg) s += '<br>上次 ' + (when ? when + ' · ' : '') + (j.auto_msg || '');
  }
  el.innerHTML = s;
}
/* 打开"更新"页时同步一次自动更新开关的真实状态 (不依赖检查结果) */
async function autoLoad() {
  try {
    const s = await (await fetch('/api/settings', { cache: 'no-store' })).json();
    const cb = document.getElementById('upd-auto'), el = document.getElementById('upd-autohint');
    if (!cb || !el) return;
    cb.checked = !!s.auto_update;
    let txt = s.auto_update
      ? '已开启: 每 5 分钟检查一次, 发现新版本且没人看视频时自动升级'
      : '已关闭: 只用下方按钮手动升级';
    const when = s.auto_checked ? new Date(s.auto_checked * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '';
    if (s.auto_update && (when || s.auto_msg)) txt += '<br>上次 ' + (when ? when + ' · ' : '') + (s.auto_msg || '');
    el.innerHTML = txt;
  } catch (e) {}
}
async function setAutoUpdate(on) {
  const cb = document.getElementById('upd-auto'), el = document.getElementById('upd-autohint');
  try {
    const j = await (await fetch('/api/ota/auto', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ on: !!on })
    })).json();
    if (!j.ok) throw new Error(j.msg || '保存失败');
    el.innerHTML = on
      ? '已开启: 每 5 分钟检查一次, 发现新版本且没人看视频时自动升级'
      : '已关闭: 只用下方按钮手动升级';
    if (on) setTimeout(() => otaCheck(false), 800);
  } catch (e) {
    cb.checked = !on;
    toast('❌ 自动更新设置失败: ' + (e.message || e));
  }
}
/* 服务重启期间轮询, 起来后自动刷新页面 */
async function otaWaitBack() {
  for (let i = 0; i < 40; i++) {
    await new Promise(r => setTimeout(r, 1500));
    try {
      const r = await fetch('/api/live', { cache: 'no-store' });
      if (r.ok) { location.reload(); return; }
    } catch (e) {}
  }
  location.reload();
}
async function otaApply() {
  if (!otaInfo || !otaInfo.has_update) return;
  if (!confirm('升级到 v' + otaInfo.latest + ' ?\n程序文件会被覆盖, 服务自动重启约 5 秒, 期间页面会短暂打不开。')) return;
  const btn = document.getElementById('upd-go'), msg = document.getElementById('upd-msg');
  btn.disabled = true;
  msg.textContent = t('正在下载并校验新版本…');
  try {
    const j = await (await fetch('/api/ota/apply', { method: 'POST' })).json();
    msg.textContent = j.msg;
    if (!j.ok) { btn.disabled = false; return; }
    otaWaitBack();
  } catch (e) {
    msg.textContent = t('升级失败') + ': ' + e;
    btn.disabled = false;
  }
}
async function otaRollback() {
  if (!confirm('回滚到升级前的版本?\n适合新版本出现问题时使用, 服务会自动重启。')) return;
  const msg = document.getElementById('upd-msg');
  msg.textContent = '正在回滚…';
  try {
    const j = await (await fetch('/api/ota/rollback', { method: 'POST' })).json();
    msg.textContent = j.msg;
    if (j.ok) otaWaitBack();
  } catch (e) { msg.textContent = '回滚失败: ' + e; }
}
/* 打开首页后静默检查一次 (结果缓存 10 分钟), 有新版本时齿轮上亮红点 */
setTimeout(() => {
  fetch('/api/ota/check', { cache: 'no-store' }).then(r => r.json()).then(j => {
    if (j && j.has_update) {
      const g = document.getElementById('gear');
      g.classList.add('hasupd');
      g.title = '有新版本 v' + j.latest + ' · 点开设置可升级';
    }
  }).catch(() => {});
}, 5000);
document.getElementById('gear').onclick = () => {
  document.getElementById('mask').classList.add('open');
  document.getElementById('panel').classList.add('open');
  stab('files');
  refreshSkins(); refreshAudio(); refreshFiles();
};
function closePanel() {
  document.getElementById('mask').classList.remove('open');
  document.getElementById('panel').classList.remove('open');
}

async function uploadFile(input, url, fields) {
  const f = input.files[0]; if (!f) return;
  const fd = new FormData(); fd.append('file', f);
  for (const k in (fields || {})) fd.append(k, fields[k]);
  const r = await fetch(url, { method: 'POST', body: fd });
  const j = await r.json();
  toast(j.ok ? '✅ ' + j.msg : '❌ ' + j.msg);
  input.value = '';
  return j;
}

/* 皮肤 */
async function refreshSkins() {
  const j = await (await fetch('/api/skins')).json();
  const list = document.getElementById('skin-list'); list.innerHTML = '';
  if (!j.skins.length) { list.innerHTML = '<div class="hint">暂无皮肤, 使用默认外观</div>'; return; }
  for (const s of j.skins) {
    const d = document.createElement('div'); d.className = 'item';
    d.innerHTML = `<span class="n">${s}</span>` + (s === j.active ? '<span class="tag">使用中</span>' : '') +
      (s === j.active ? '' : `<button class="primary" onclick="applySkin('${s}')">应用</button>`) +
      `<button class="danger" onclick="delSkin('${s}')">删除</button>`;
    list.appendChild(d);
  }
}
async function applySkin(s) {
  await fetch('/api/skin/activate', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ name: s }) });
  toast('皮肤已应用: ' + s); injectSkin(); refreshSkins();
}
async function delSkin(s) {
  if (!confirm('删除皮肤 ' + s + ' ?')) return;
  await fetch('/api/skin/' + encodeURIComponent(s), { method: 'DELETE' });
  toast('已删除'); injectSkin(); refreshSkins();
}
async function injectSkin() {
  let el = document.getElementById('userskin');
  if (!el) { el = document.createElement('style'); el.id = 'userskin'; document.head.appendChild(el); }
  const r = await fetch('/api/skin');
  el.textContent = r.ok ? await r.text() : '';
}
document.getElementById('skin-file').onchange = async function () {
  const j = await uploadFile(this, '/api/upload/skin');
  if (j && j.ok) { refreshSkins(); if (j.activated) { injectSkin(); } }
};

/* 品牌: 标题栏的图标与名称 (服务端存 settings.json, 所有访客共用一套) */
const BRAND = { custom: '', logo: '', ver: 0 };
const BRAND_DEFAULT_NAME = 'TSL哨兵云盘';
function brandName() { return BRAND.custom || BRAND_DEFAULT_NAME; }
function brandLogoURL() { return '/api/brand/logo?v=' + (BRAND.ver || 'd'); }
function applyBrand() {
  const nm = brandName();
  const n = document.getElementById('bname');
  if (n) n.textContent = nm;
  const p = document.getElementById('brand-prevname');
  if (p) p.textContent = nm;
  document.title = nm;
  const u = brandLogoURL();
  ['blogo', 'brand-prev'].forEach(id => {
    const el = document.getElementById(id);
    if (el && el.getAttribute('src') !== u) el.src = u;
  });
}
async function refreshBrand() {
  try {
    const j = await (await fetch('/api/settings', { cache: 'no-store' })).json();
    BRAND.custom = (j.brand_name || '').trim();
    BRAND.logo = j.brand_logo || '';
    BRAND.ver = j.brand_logo_v || 0;
  } catch (e) { /* 拿不到就用默认 */ }
  applyBrand();
  const inp = document.getElementById('brand-name');
  if (inp) inp.value = BRAND.custom;
}
async function saveBrandName() {
  const inp = document.getElementById('brand-name');
  const v = ((inp && inp.value) || '').trim();
  const j = await (await fetch('/api/brand/name', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: v }) })).json();
  if (!j.ok) { toast('❌ ' + (j.msg || '保存失败')); return; }
  BRAND.custom = v;
  applyBrand();
  toast(v ? '✅ 名称已改为 ' + v : '✅ 已恢复默认名称');
}
document.getElementById('brand-file').onchange = async function () {
  const j = await uploadFile(this, '/api/upload/brand-logo');
  if (j && j.ok) { await refreshBrand(); }
};
async function resetBrand() {
  if (!confirm('恢复默认图标与名称?')) return;
  const j = await (await fetch('/api/brand/reset', { method: 'POST' })).json();
  if (!j.ok) { toast('❌ ' + (j.msg || '操作失败')); return; }
  BRAND.custom = ''; BRAND.logo = ''; BRAND.ver = Date.now();
  const inp = document.getElementById('brand-name');
  if (inp) inp.value = '';
  applyBrand();
  toast('✅ 已恢复默认');
}

/* 锁车语音 */
async function refreshAudio() {
  const j = await (await fetch('/api/audio')).json();
  const mk = (arr, elid, isDone) => {
    const list = document.getElementById(elid); list.innerHTML = '';
    if (!arr.length) { list.innerHTML = '<div class="hint" style="margin:0">无</div>'; return; }
    for (const f of arr) {
      const d = document.createElement('div'); d.className = 'item';
      const lockTag = f === 'LockChime.wav' ? '<span class="tag">锁车音</span>' : '';
      d.innerHTML = `<span class="n">${f}</span>${lockTag}` +
        (isDone ? '' : `<button class="primary" onclick="setLock('${f}')">设为锁车音</button>`) +
        `<button class="danger" onclick="delAudio('${f}',${isDone})">删除</button>`;
      list.appendChild(d);
    }
  };
  mk(j.queue, 'audio-list', false);
  mk(j.done, 'audio-done', true);
}
async function setLock(f) {
  const r = await fetch('/api/audio/setlockchime', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ name: f }) });
  const j = await r.json();
  toast(j.ok ? '✅ 已设为锁车音 (LockChime.wav)' : '❌ ' + j.msg);
  refreshAudio();
}
async function delAudio(f, isDone) {
  if (!confirm('删除 ' + f + ' ?')) return;
  await fetch('/api/audio/' + encodeURIComponent(f) + '?done=' + (isDone ? 1 : 0), { method: 'DELETE' });
  refreshAudio();
}
document.getElementById('audio-file').onchange = async function () {
  const j = await uploadFile(this, '/api/upload/audio');
  if (j && j.ok) refreshAudio();
};

/* 文件管理器 */
let curDir = '';
let area = 'usb';  // 'usb' = 车机U盘镜像, 'archive' = 归档区
let fmSel = new Set();      // 已勾选的完整路径
let fmPending = null;       // 等待填目标目录的移动/复制任务
let usbAttached = false;    // 车机U盘是否处于网页管理(已挂载)状态
function fmtSize(n) {
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1048576).toFixed(1) + ' MB';
}
function fmUpdate() {
  const cnt = document.getElementById('fm-count');
  if (!cnt) return;
  cnt.textContent = '已选 ' + fmSel.size + ' 项';
  const all = document.getElementById('fm-all');
  const boxes = Array.from(document.querySelectorAll('#file-list .fm-chk'));
  const on = boxes.filter(b => b.checked).length;
  all.checked = boxes.length > 0 && on === boxes.length;
  all.indeterminate = on > 0 && on < boxes.length;
}
function fmToggle(p, checked, row) {
  if (checked) fmSel.add(p); else fmSel.delete(p);
  if (row) row.classList.toggle('fm-sel', !!checked);
  fmUpdate();
}
function fmAll(checked) {
  fmSel.clear();
  document.querySelectorAll('#file-list .fm-chk').forEach(b => {
    b.checked = checked;
    const row = b.closest('.item');
    if (row) row.classList.toggle('fm-sel', !!checked);
    if (checked) fmSel.add(b.dataset.p);
  });
  fmUpdate();
}
function fmDestCancel() {
  fmPending = null;
  const box = document.getElementById('fm-dest');
  if (box) box.style.display = 'none';
}
function fmOp(op) {
  if (!fmSel.size) { toast('请先勾选文件或文件夹'); return; }
  const items = Array.from(fmSel);
  if (op === 'rename') {
    if (items.length !== 1) { toast('重命名只能选中一项'); return; }
    const cur = items[0].split('/').pop();
    const nn = prompt('新名称 (可含中文):', cur);
    if (!nn || nn === cur) return;
    fmSend({ area, op, items, name: nn });
    return;
  }
  if (op === 'delete') {
    const preview = items.slice(0, 3).map(x => x.split('/').pop()).join('、');
    if (!confirm('确定删除选中的 ' + items.length + ' 项吗？\n' + preview + (items.length > 3 ? ' …' : '') +
      '\n\n文件夹会连同里面所有内容一起删除，且不可恢复。')) return;
    fmSend({ area, op, items });
    return;
  }
  fmPending = { area, op, items };
  const box = document.getElementById('fm-dest');
  const inp = document.getElementById('fm-dest-input');
  box.style.display = 'flex';
  inp.value = curDir;
  inp.placeholder = area === 'usb' ? '目标目录, 留空=U盘根目录' : '目标目录, 如 /archive/files';
  inp.focus();
}
function fmDestGo() {
  if (!fmPending) return;
  const dest = document.getElementById('fm-dest-input').value.trim();
  if (area === 'usb' && dest.startsWith('/')) { toast('车机U盘请填相对路径 (留空=根目录)'); return; }
  if (area === 'archive' && !dest.startsWith('/archive')) { toast('归档区请填 /archive 开头的绝对路径'); return; }
  const b = fmPending;
  fmDestCancel();
  const verb = b.op === 'move' ? '移动' : '复制';
  if (!confirm('把选中的 ' + b.items.length + ' 项' + verb + '到\n' + (dest || '(U盘根目录)') +
    ' ?\n\n同名会被跳过；复制大视频可能占满U盘空间。')) return;
  fmSend({ area: b.area, op: b.op, items: b.items, dest });
}
async function fmSend(payload) {
  toast('⏳ 正在处理…');
  let j;
  try {
    const r = await fetch('/api/fm', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    j = await r.json();
  } catch (e) { toast('❌ 请求失败: ' + e); return; }
  let msg = (j.ok ? '✅ ' : '❌ ') + (j.msg || '');
  if (j.failed && j.failed.length) msg += ' | ' + j.failed.slice(0, 2).join('; ');
  toast(msg);
  fmSel.clear();
  fmDestCancel();
  refreshFiles();
}
async function purgeTeslaCam() {
  if (area !== 'usb') { toast('请先切换到「车机U盘」'); return; }
  if (!usbAttached) { toast('请先点「连接车机U盘」, 连上后才能清空录像'); return; }
  if (!confirm('⚠️ 将永久删除车机U盘 TeslaCam/ 内的全部录像文件与事件文件夹。\n\n' +
    '• 保留 TeslaCam 及 RecentClips / SavedClips / SentryClips 目录结构\n' +
    '• 不影响 Boombox、Wraps 等其他根目录\n' +
    '• 需先连接 U 盘 (会临时断开车机读取)\n\n确定继续吗？')) return;
  if (!confirm('再次确认：此操作不可撤销，确认清空全部录像？')) return;
  await fmSend({ area: 'usb', op: 'purge_teslacam', items: [] });
}
/* ---------- 涂装 (Wraps) ---------- */
let wrapAttached = false;   // 与文件管理共用同一个 U 盘管理状态
function wrapStatusHtml(attached) {
  if (!attached) {
    return '<div style="background:#3a2a12;border-radius:10px;padding:10px 12px;font-size:12.5px;color:#f0b429;line-height:1.6">' +
      '⚠ U盘当前未连接管理 (车机正常读写中)<br>' +
      '<button onclick="wrapAttach()" style="background:#e8443f;border:none;color:#fff;border-radius:8px;padding:7px 16px;font-size:12.5px;cursor:pointer;margin-top:6px"><svg class="ic"><use href="#i-link"/></svg>连接车机U盘 (临时断开车机读取)</button></div>';
  }
  return '<div style="background:#1a3325;border-radius:10px;padding:10px 12px;font-size:12.5px;color:#4cc38a;line-height:1.6">' +
    '🟢 已连接 — 上传的图片会直接写入车机U盘 Wraps/ 目录<br>' +
    '<span style="color:#7d8894;font-size:11.5px">断开满 5 分钟无操作会自动恢复车机导出</span><br>' +
    '<button onclick="wrapDetach()" style="background:#242c35;border:none;color:#e8eaed;border-radius:8px;padding:7px 16px;font-size:12.5px;cursor:pointer;margin-top:6px">✅ 恢复车机导出</button></div>';
}
async function wrapAttach() {
  toast('⏳ 正在连接 (车机读取将断开几秒)...');
  const j = await (await fetch('/api/usb/attach', { method: 'POST' })).json();
  toast(j.ok ? '✅ 已连接车机U盘' : '❌ ' + j.msg);
  await refreshWraps();
}
async function wrapDetach() {
  const j = await (await fetch('/api/usb/detach', { method: 'POST' })).json().catch(() => ({}));
  toast(j.ok ? '✅ ' + t('已恢复车机导出') : '❌ ' + t(j.msg || '恢复失败'));
  await refreshWraps();
}
async function refreshWraps() {
  const st = document.getElementById('wraps-status');
  const grid = document.getElementById('wraps-grid');
  let j;
  try {
    j = await (await fetch('/api/usb/browse?dir=' + encodeURIComponent('Wraps'))).json();
  } catch (e) { return; }
  wrapAttached = !!j.attached;
  st.innerHTML = wrapStatusHtml(wrapAttached);
  grid.innerHTML = '';
  if (!j.ok) {
    grid.innerHTML = wrapAttached
      ? '<div class="hint">Wraps 目录不存在, 上传图片会自动创建</div>'
      : '<div class="hint">U盘未连接管理 (车机正常读写中), 点上方「连接车机U盘」后可查看 / 上传图片</div>';
    return;
  }
  const files = j.files || [];
  if (!files.length) { grid.innerHTML = '<div class="hint">Wraps 目录为空, 上传图片即可在车机上选用</div>'; return; }
  for (const f of files) {
    const box = document.createElement('div');
    box.style.cssText = 'width:110px;text-align:center';
    const img = document.createElement('img');
    img.src = '/usbdl?path=' + encodeURIComponent('Wraps/' + f.name);
    img.style.cssText = 'width:100px;height:68px;object-fit:contain;background:#0d1117;border-radius:8px;border:1px solid #2a3440;cursor:pointer';
    img.onclick = () => window.open('/usbdl?path=' + encodeURIComponent('Wraps/' + f.name));
    const cap = document.createElement('div');
    cap.textContent = f.name;
    cap.style.cssText = 'font-size:11px;color:#c9d1d9;margin:4px 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
    const btn = document.createElement('button');
    btn.className = 'danger'; btn.textContent = t('删除');
    btn.style.cssText = 'font-size:11px;padding:4px 12px';
    btn.onclick = async () => {
      if (!confirm(t('删除') + ' Wraps/' + f.name + ' ?')) return;
      const r = await fetch('/api/usb?path=' + encodeURIComponent('Wraps/' + f.name), { method: 'DELETE' });
      const rj = await r.json().catch(() => ({}));
      toast(rj.ok ? '✅ ' + t('已删除') : '❌ ' + (rj.msg || t('删除失败')));
      refreshWraps();
    };
    box.append(img, cap, btn);
    grid.appendChild(box);
  }
}
document.getElementById('wraps-file').onchange = async function () {
  if (!this.files || !this.files.length) return;
  if (!wrapAttached) { toast('请先点「连接车机U盘」, 连上后再上传'); this.value = ''; return; }
  for (const f of this.files) {
    const fd = new FormData(); fd.append('file', f); fd.append('path', 'Wraps');
    try {
      const r = await fetch('/api/upload/usb', { method: 'POST', body: fd });
      const j = await r.json();
      toast((j.ok ? '✅ ' : '❌ ') + f.name + ' — ' + (j.msg || ''));
    } catch (e) { toast('❌ ' + f.name + ' — ' + t('上传失败')); }
  }
  this.value = '';
  await refreshWraps();
};
function escH(s) { return String(s || '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function fmtSz(n) { n = +n || 0; const u = ['B','K','M','G','T']; let i = 0; while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; } return (i ? n.toFixed(1) : n) + u[i]; }
let storageData = null;
function storageFindPart(dev) {
  for (const d of (storageData && storageData.disks) || []) for (const p of d.parts) if (p.dev === dev) return {disk: d, part: p};
  return null;
}
function storageFindDisk(dev) {
  for (const d of (storageData && storageData.disks) || []) if (d.disk === dev) return d;
  return null;
}
function storageSerial(d) { return d ? (d.serial || d.disk.split('/').pop()) : ''; }
async function refreshStorage() {
  const st = document.getElementById('storage-status'), box = document.getElementById('storage-disks');
  let j;
  try { j = await (await fetch('/api/storage/status')).json(); } catch (e) { st.textContent = '存储状态读取失败'; return; }
  if (!j.ok) { st.textContent = j.msg || '存储状态读取失败'; return; }
  storageData = j;
  const linked = j.host_connected === true;
  st.innerHTML = '外接存储: ' + (j.storage_ready ? '<span class="storage-ok">已挂载</span>' : '<span class="storage-warn">未挂载 · 当前仅可管理存储，不会写入系统盘</span>') + '<br>' +
    'OTG 连接: ' + (linked ? '<span class="storage-ok">已连接主机</span>' : '<span class="storage-warn">未连接主机</span>') +
    ' <span class="storage-meta">(' + escH(j.udc || '无 UDC') + ' / ' + escH(j.state || '未知') + ' / ' + escH(j.speed || '未知速率') + ')</span><br>' +
    '虚拟U盘容量: ' + fmtSz(j.img_size) + ' (实际占用 ' + fmtSz(j.img_used) + ')<br>' +
    '镜像: <span class="storage-meta">' + escH(j.img) + '</span><br>' +
    '当前存储: ' + escH(j.source || (j.storage_ready ? '未知' : '未挂载')) + ' · 归档: <span class="storage-meta">' + escH(j.archive) + '</span><br>' +
    'USB 序列号: <b>' + escH(j.gadget_serial || '无') + '</b> · 卷序列号: <b>' + escH(j.volume_serial || '无') + '</b>';
  let h = '';
  for (const d of j.disks || []) {
    h += '<div class="storage-disk">💾 ' + escH(d.disk) + ' ' + escH(d.size) + ' ' + escH(d.model) + ' · 序列号: <b>' + escH(storageSerial(d)) + '</b></div>';
    for (const p of d.parts) {
      const cur = p.dev === j.source;
      h += '<div class="storage-part">' +
        '<span class="storage-part-name">' + escH(p.dev) + ' ' + escH(p.size) + ' ' + escH(p.fstype || '无文件系统') + '</span>' +
        (cur ? '<span class="storage-current">当前使用</span>' :
          '<button class="storage-use" onclick="storageUse(\'' + p.dev + '\')">使用此盘</button>' +
          '<button class="storage-format" onclick="storageFormat(\'' + p.dev + '\')"' + (linked ? ' disabled' : '') + '>格式化</button>') +
        (p.mount ? '<span class="storage-mount">' + escH(p.mount) + '</span>' : '') + '</div>';
    }
  }
  box.innerHTML = h || '<div class="hint">未检测到 USB 硬盘</div>';
  const sel = document.getElementById('alloc-device'), old = sel.value;
  sel.innerHTML = '';
  for (const d of j.disks || []) {
    const op = document.createElement('option');
    op.value = d.disk;
    op.textContent = d.disk + ' · ' + d.size + ' · ' + (d.model || 'USB硬盘') + ' · 序列号 ' + storageSerial(d);
    sel.appendChild(op);
  }
  if (old) sel.value = old;
  else {
    const current = storageFindPart(j.source);
    if (current) sel.value = current.disk.disk;
  }
  storageAllocCalc();
  const initBtn = document.querySelector('.storage-init');
  initBtn.disabled = linked;
  initBtn.title = linked ? 'OTG 已连接主机, 请先拔出数据线' : '';
}
function storageAllocCalc() {
  const pct = +document.getElementById('alloc-percent').value;
  document.getElementById('alloc-percent-text').textContent = pct + '%';
  const dev = document.getElementById('alloc-device').value, info = storageFindDisk(dev), out = document.getElementById('alloc-calc');
  if (!info) { out.textContent = '请选择要分配的 USB 硬盘'; return; }
  const total = info.size_bytes / 1073741824;
  const v = Math.floor(total * pct / 100), a = Math.floor(total) - v;
  out.innerHTML = '虚拟U盘: <b>' + v + 'G</b> · 归档区: <b>' + a + 'G</b> (整块硬盘约 ' + total.toFixed(1) + 'G)';
}
async function storageInit() {
  const dev = document.getElementById('alloc-device').value;
  const pct = +document.getElementById('alloc-percent').value;
  const info = storageFindDisk(dev);
  if (!info) { toast('请选择硬盘'); return; }
  if (storageData && storageData.host_connected) { toast('❌ OTG 已连接主机, 请先拔出数据线'); return; }
  if (!confirm('第一遍确认：此操作会清空整块硬盘 ' + dev + '，包括全部分区。\n确定要继续吗？')) return;
  const serial = storageSerial(info);
  const c = prompt('第二遍确认：请输入该盘序列号完成最终确认。\n序列号: ' + serial);
  if (c === null) return;
  if (c !== serial) { toast('序列号不一致, 已取消'); return; }
  toast('⏳ 正在格式化并创建虚拟U盘, 请稍候...');
  try {
    const j = await (await fetch('/api/storage/init', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({device: dev, percent: pct, confirm: c}) })).json();
    toast(j.ok ? '✅ ' + j.msg : '❌ ' + j.msg);
    if (j.ok && j.msg.indexOf('刷新') >= 0) setTimeout(() => location.reload(), 4000);
    else refreshStorage();
  } catch (e) { toast('❌ 初始化失败'); }
}
async function storageUse(dev) {
  if (!confirm('把镜像和归档迁移到 ' + dev + ' ?\n过程中车机U盘会短暂断开, 完成后页面自动刷新。')) return;
  toast('⏳ 正在切换存储盘, 数据较多时请耐心等待...');
  try {
    const j = await (await fetch('/api/storage/use', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({device: dev}) })).json();
    toast(j.ok ? '✅ ' + j.msg : '❌ ' + j.msg);
    if (j.ok && j.msg.indexOf('刷新') >= 0) setTimeout(() => location.reload(), 4000);
    else refreshStorage();
  } catch (e) { toast('❌ 切换失败'); }
}
async function storageFormat(dev) {
  if (storageData && storageData.host_connected) { toast('❌ OTG 已连接主机, 请先拔出数据线'); return; }
  if (!confirm('第一遍确认：格式化会清空 ' + dev + ' 上的全部数据！\n确定要继续吗？')) return;
  const info = storageFindPart(dev), serial = storageSerial(info && info.disk);
  const c = prompt('第二遍确认：请输入该盘序列号完成最终确认。\n序列号: ' + serial);
  if (c === null) return;
  if (c !== serial) { toast('序列号不一致, 已取消'); return; }
  toast('⏳ 正在格式化...');
  try {
    const j = await (await fetch('/api/storage/format', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({device: dev, confirm: c}) })).json();
    toast(j.ok ? '✅ 已格式化, 可点击「使用此盘」' : '❌ ' + j.msg);
  } catch (e) { toast('❌ 格式化失败'); }
  refreshStorage();
}
refreshStorage();
function switchArea(a) {
  area = a;
  document.getElementById('area-usb').classList.toggle('active', a === 'usb');
  document.getElementById('area-archive').classList.toggle('active', a === 'archive');
  document.getElementById('usb-hint').style.display = a === 'usb' ? '' : 'none';
  document.getElementById('arch-hint').style.display = a === 'archive' ? '' : 'none';
  document.getElementById('purge-box').style.display = a === 'usb' ? 'flex' : 'none';
  document.getElementById('storage-panel').style.display = a === 'usb' ? '' : 'none';
  if (a === 'usb') refreshStorage();
  curDir = a === 'usb' ? '' : '/archive/files';
  refreshFiles();
}
function usbStatusHtml(attached, msg) {
  if (!attached) {
    return '<div style="background:#3a2a12;border-radius:10px;padding:10px 12px;font-size:12.5px;color:#f0b429;line-height:1.6">' +
      '⚠ U盘当前未连接管理 (车机正常读写中)<br>' +
      '<button onclick="usbAttach()" style="background:#e8443f;border:none;color:#fff;border-radius:8px;padding:7px 16px;font-size:12.5px;cursor:pointer;margin-top:6px"><svg class="ic"><use href="#i-link"/></svg>连接车机U盘 (临时断开车机读取)</button></div>';
  }
  return '<div style="background:#1a3325;border-radius:10px;padding:10px 12px;font-size:12.5px;color:#4cc38a;line-height:1.6">' +
    '🟢 已连接 — U盘已从车机临时断开, 你在网页上的改动会直接写入车机U盘<br>' +
    '<span style="color:#7d8894;font-size:11.5px">断开满 5 分钟无操作会自动恢复车机导出</span><br>' +
    '<button onclick="usbDetach()" style="background:#242c35;border:none;color:#e8eaed;border-radius:8px;padding:7px 16px;font-size:12.5px;cursor:pointer;margin-top:6px">✅ 恢复车机导出</button></div>';
}
async function usbAttach() {
  toast('⏳ 正在连接 (车机读取将断开几秒)...');
  const r = await fetch('/api/usb/attach', { method: 'POST' });
  const j = await r.json();
  toast(j.ok ? '✅ 已连接车机U盘' : '❌ ' + j.msg);
  curDir = '';
  refreshFiles();
}
async function usbDetach() {
  const j = await (await fetch('/api/usb/detach', { method: 'POST' })).json();
  toast(j.ok ? '✅ ' + t('已恢复车机导出') : '❌ ' + t(j.msg));
  document.getElementById('dir-nav').style.display = 'none';
  refreshFiles();
}
function goDir(d) {
  if (area === 'usb') {
    d = (d || '').trim().replace(/^\/+|\/+$/g, '');
    refreshFiles(d);
  } else {
    d = (d || '').trim().replace(/\/+$/, '') || '/archive';
    if (!d.startsWith('/archive')) { toast('❌ 仅支持 /archive 内的路径'); return; }
    refreshFiles(d);
  }
}
async function refreshFiles(dir) {
  if (dir !== undefined) curDir = dir;
  fmSel.clear();
  fmDestCancel();
  const statusEl = document.getElementById('usb-status');
  const nav = document.getElementById('dir-nav');
  const crumb = document.getElementById('crumb');
  const list = document.getElementById('file-list');
  let j;
  if (area === 'usb') {
    j = await (await fetch('/api/usb/browse?dir=' + encodeURIComponent(curDir))).json();
    statusEl.style.display = 'block';
    statusEl.innerHTML = usbStatusHtml(j.attached, j.msg);
    usbAttached = !!j.attached;
    if (!j.attached) { nav.style.display = 'none'; list.innerHTML = ''; fmUpdate(); return; }
    nav.style.display = 'block';
  } else {
    j = await (await fetch('/api/browse?dir=' + encodeURIComponent(curDir))).json();
    statusEl.style.display = 'none';
    if (!j.ok) { toast('❌ ' + (j.msg || '目录不可访问')); return; }
    nav.style.display = 'block';
  }
  curDir = area === 'usb' ? j.dir : j.dir;
  document.getElementById('dest-dir').value = curDir;
  crumb.innerHTML = '';
  const mkLink = (label, target, folder) => {
    const a = document.createElement('a');
    a.textContent = label; a.href = 'javascript:void(0)';
    a.style.cssText = 'color:' + (folder ? '#5ea9ff' : '#7d8894') + ';cursor:pointer;text-decoration:underline';
    a.onclick = () => goDir(target);
    crumb.appendChild(a);
    const s = document.createElement('span'); s.textContent = ' / '; s.style.color = '#3a4652';
    crumb.appendChild(s);
  };
  if (area === 'usb') {
    mkLink('🚗 U盘根目录', '', true);
    let acc = '';
    for (const seg of curDir.split('/').filter(Boolean)) {
      acc = acc ? acc + '/' + seg : seg;
      mkLink(seg, acc, true);
    }
  } else {
    let acc = '';
    for (const seg of curDir.split('/').filter(Boolean)) { acc += '/' + seg; mkLink(seg, acc, true); }
  }
  list.innerHTML = '';
  let empty = true;
  const mkChk = (full, row) => {
    const c = document.createElement('input');
    c.type = 'checkbox'; c.className = 'fm-chk'; c.dataset.p = full;
    c.onchange = () => fmToggle(full, c.checked, row);
    return c;
  };
  for (const d of j.dirs) {
    empty = false;
    const full = area === 'usb' ? (curDir ? curDir + '/' + d : d) : curDir + '/' + d;
    const el = document.createElement('div'); el.className = 'item';
    const n = document.createElement('span'); n.className = 'n';
    n.textContent = '📁 ' + d; n.style.cssText = 'cursor:pointer;color:#5ea9ff';
    n.onclick = () => goDir(full);
    el.append(mkChk(full, el), n);
    list.appendChild(el);
  }
  for (const f of j.files) {
    empty = false;
    const full = area === 'usb' ? (curDir ? curDir + '/' + f.name : f.name) : curDir + '/' + f.name;
    const el = document.createElement('div'); el.className = 'item';
    const n = document.createElement('span'); n.className = 'n'; n.textContent = f.name;
    const tag = document.createElement('span'); tag.className = 'tag'; tag.textContent = fmtSize(f.size || 0);
    const btnDl = document.createElement('button'); btnDl.className = 'primary fm-mini';
    btnDl.textContent = '⬇'; btnDl.title = t('下载');
    btnDl.onclick = async () => {
      const url = (area === 'usb' ? '/usbdl?path=' : '/dl?path=') + encodeURIComponent(full);
      if (area !== 'usb') { location.href = url; return; }   // 归档区可能是大视频, 走浏览器流式下载
      try {   // U盘文件多为小件: fetch 成 blob, 失败只弹提示, 不再整页跳走
        const r = await fetch(url);
        if (!r.ok) { toast('❌ ' + t('文件读不到, U盘可能已自动恢复车机导出, 请重新连接')); return; }
        const b = await r.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(b); a.download = f.name;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 60000);
      } catch (e) { toast('❌ ' + t('下载失败')); }
    };
    const btnDel = document.createElement('button'); btnDel.className = 'danger fm-mini';
    btnDel.textContent = '✕'; btnDel.title = t('删除');
    btnDel.onclick = () => delFile(full);
    el.append(mkChk(full, el), n, tag, btnDl, btnDel);
    list.appendChild(el);
  }
  if (empty) list.innerHTML = '<div class="hint" style="margin:0">' + t('空目录') + '</div>';
  fmUpdate();
}
async function delFile(p) {
  if (!confirm('删除 ' + (area === 'usb' ? 'U盘/' : '') + p + ' ?')) return;
  const url = area === 'usb' ? '/api/usb?path=' : '/api/file?path=';
  await fetch(url + encodeURIComponent(p), { method: 'DELETE' });
  toast('已删除'); refreshFiles();
}
document.getElementById('anyfile-file').onchange = async function () {
  const url = area === 'usb' ? '/api/upload/usb' : '/api/upload/file';
  const j = await uploadFile(this, url, { path: area === 'usb' ? curDir : curDir });
  if (j && j.ok) refreshFiles();
};

injectSkin();
applyLang();
refreshBrand();
load();
// 字体状态预热: 这时还没开播放器, 连接池是空的, 一定能拿到
loadFontInfo().then(paintFont);
</script></body></html>"""


def ensure_dirs():
    # 外接盘未挂载时只允许网页进入存储管理模式, 不能在根文件系统创建归档目录。
    if not storage_ready():
        print("external storage not mounted; viewer starts in storage-management-only mode")
        return False
    for d in (SKIN_DIR, AUDIO_Q, AUDIO_DONE, FILES_DIR, ARCHIVE):
        os.makedirs(d, exist_ok=True)
    for c in CATS:
        os.makedirs(os.path.join(ARCHIVE, c), exist_ok=True)
    os.makedirs(RES_DIR, exist_ok=True)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    return True


def safe_name(name):
    name = os.path.basename(name or "")
    return name if re.match(r'^[\w\-. ]{1,80}$', name) else None


def list_events():
    out = {}
    for cat in CATS:
        base = os.path.join(ARCHIVE, cat)
        events = []
        if os.path.isdir(base):
            for name in sorted(os.listdir(base), reverse=True):
                d = os.path.join(base, name)
                if not os.path.isdir(d):
                    continue
                vids = []
                total = 0
                for f in sorted(os.listdir(d)):
                    if f.lower().endswith(".mp4"):
                        cam = f.rsplit("-", 1)[-1][:-4] if "-" in f else f
                        vids.append({"url": f"/media/{cat}/{name}/{f}", "cam": cam, "f": f})
                        try:
                            total += os.path.getsize(os.path.join(d, f))
                        except OSError:
                            pass
                meta = {}
                ej = os.path.join(d, "event.json")
                if os.path.isfile(ej):
                    try:
                        with open(ej, "r", encoding="utf-8", errors="ignore") as jf:
                            meta = json.load(jf)
                    except Exception:
                        meta = {}
                events.append({"name": name, "videos": vids, "size": total, "meta": meta})
        out[cat] = events
    return out


def _map_archive(p):
    """前端与深链固定用 /archive/... 作为虚拟前缀; 归档区可配置时映射到实际目录"""
    if ARCHIVE != "/archive" and (p == "/archive" or p.startswith("/archive/")):
        return ARCHIVE + p[len("/archive"):]
    return p


def _unmap_archive(p):
    """接口返回前端虚拟路径, 不把 /mnt/... 等服务器内部路径显示成面包屑"""
    root = ARCHIVE.rstrip("/")
    if ARCHIVE != "/archive":
        if p == root:
            return "/archive"
        if p.startswith(root + "/"):
            return "/archive" + p[len(root):]
    return p


def safe_archive_dir(p):
    """校验目录必须落在归档区内 (防路径逃逸), 返回 realpath 或 None"""
    if not storage_ready():
        return None
    p = _map_archive((p or "").strip())
    if not p.startswith(ARCHIVE):
        return None
    rp = os.path.realpath(p)
    root = os.path.realpath(ARCHIVE)
    if rp != root and not rp.startswith(root + "/"):
        return None
    return rp


def safe_archive_path(p):
    """校验文件路径必须落在归档区内且真实存在"""
    if not storage_ready():
        return None
    p = _map_archive((p or "").strip())
    if not p.startswith(ARCHIVE):
        return None
    rp = os.path.realpath(p)
    if not rp.startswith(os.path.realpath(ARCHIVE) + "/") or not os.path.isfile(rp):
        return None
    return rp


# ---------- 车机U盘(镜像)临时管理 ----------
IMG = os.environ.get("TSF_IMG", "/root/teslacam.img")
MNT = os.environ.get("TSF_MNT", "/tmp/teslamnt")
LOOPDEV = os.environ.get("TSF_LOOP", "/dev/loop3")
LOSETUP = os.environ.get("TSF_LOSETUP") or "losetup"
GADGET_DIR = os.environ.get("TSF_GADGET", "/sys/kernel/config/usb_gadget/g1")
USB_AUTO_DETACH = 300  # 秒, 无操作自动恢复导出
# 跨进程 U 盘互斥: 网页挂载(排他) / tesla-sync.sh(排他) / usb-selfheal.sh(排他) /
# tesla-live-sync.py(共享) 共用同一锁文件; 排他锁在整个挂载周期内持有。
# 设备实测 BusyBox flock 与 Python fcntl.flock 可互锁。
USB_LOCK_FILE = os.environ.get("TSF_USB_LOCK", "/tmp/tsf-usb.lock")

usb_lock = threading.Lock()
usb_attached = False
usb_timer = None
_usb_flock_fd = None


def _acquire_usb_flock(exclusive=True):
    """拿跨进程锁, 失败立即返回 False (不排队, 由调用方跳过或重试)"""
    global _usb_flock_fd
    if _usb_flock_fd is not None:
        return True
    fd = None
    try:
        fd = os.open(USB_LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    except OSError:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        return False
    _usb_flock_fd = fd
    return True


def _release_usb_flock():
    global _usb_flock_fd
    fd, _usb_flock_fd = _usb_flock_fd, None
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def _udc():
    try:
        return os.listdir("/sys/class/udc")[0]
    except Exception:
        return None


def _gadget_rebind(bind):
    udc = _udc()
    if not udc:
        return False
    try:
        with open(os.path.join(GADGET_DIR, "UDC"), "w") as f:
            # 解绑必须写换行: 空字符串不产生 write 系统调用, 内核收不到解绑指令
            # (shell 的 echo "" > UDC 实际写的是 "\n", 故脚本里一直正常)
            f.write(udc if bind else "\n")
    except Exception:
        return False
    if bind:
        return True
    # 确认真的解绑了再返回, 避免"主机还在读盘"时设备侧读写挂载/改位图
    for _ in range(10):
        try:
            with open(os.path.join(GADGET_DIR, "UDC")) as f:
                if not f.read().strip():
                    return True
        except OSError:
            return False
        time.sleep(0.3)
    return False


def ensure_teslacam_tree():
    """读写挂载后幂等补建特斯拉标准目录: 旧镜像创建时可能漏了建目录步骤,
    根目录没有 TeslaCam 时车机不会启用行车记录/哨兵。只补目录, 不动任何文件。"""
    made = []
    for sub in ("TeslaCam", "TeslaCam/RecentClips", "TeslaCam/SavedClips",
                "TeslaCam/SentryClips", "TeslaCam/EncryptedClips"):
        d = os.path.join(MNT, sub)
        if not os.path.isdir(d):
            try:
                os.makedirs(d, exist_ok=True)
                made.append(sub)
            except OSError as ex:
                print("ensure TeslaCam dir failed:", d, ex)
    if made:
        print("ensured TeslaCam dirs:", ", ".join(made))
    return made


def usb_attach():
    """临时断开车机读取, 挂载镜像到 MNT (读写). 返回 (ok, msg)"""
    global usb_attached, usb_timer
    with usb_lock:
        if usb_attached and os.path.ismount(MNT):
            return True, "already"
        # 先拿跨进程锁再动 UDC: 归档/自愈正在操作镜像时直接让开, 不抢 loop 与挂载点。
        # 在线同步只短暂持共享锁, 等它放开即可, 避免用户偶发"点不动 U盘管理"。
        for _ in range(6):
            if _acquire_usb_flock():
                break
            time.sleep(0.4)
        else:
            return False, "U盘正被其它任务占用 (归档/自愈/同步), 稍后再试"
        try:
            os.makedirs(MNT, exist_ok=True)
        except OSError as ex:
            _release_usb_flock()
            return False, "创建挂载点失败: " + str(ex)
        if not _gadget_rebind(False):  # 停止导出
            _release_usb_flock()
            return False, "OTG 导出未能断开, 为避免与主机读写冲突本次未挂载"
        time.sleep(1)
        r = subprocess.run([LOSETUP, LOOPDEV, IMG], capture_output=True, text=True)
        if r.returncode != 0:
            _gadget_rebind(True)
            _release_usb_flock()
            return False, "losetup 失败: " + r.stderr.strip()[-120:]
        r = subprocess.run(["mount", "-t", "exfat", LOOPDEV, MNT], capture_output=True, text=True)
        if r.returncode != 0:
            subprocess.run([LOSETUP, "-d", LOOPDEV], capture_output=True)
            _gadget_rebind(True)
            _release_usb_flock()
            return False, "挂载失败: " + r.stderr.strip()[-120:]
        usb_attached = True
        ensure_teslacam_tree()
        # 无操作自动恢复
        if usb_timer:
            usb_timer.cancel()
        usb_timer = threading.Timer(USB_AUTO_DETACH, usb_detach_safe)
        usb_timer.daemon = True
        usb_timer.start()
        return True, "attached"


def usb_detach():
    """卸载镜像并恢复车机导出. 返回 (ok, msg)"""
    global usb_attached, usb_timer
    with usb_lock:
        if usb_timer:
            usb_timer.cancel()
            usb_timer = None
        if os.path.ismount(MNT):
            subprocess.run(["sync"], capture_output=True)
            for _ in range(3):
                r = subprocess.run(["umount", MNT], capture_output=True, text=True)
                if r.returncode == 0:
                    break
                time.sleep(2)
            else:
                return False, "卸载失败, 有进程占用 " + MNT
        subprocess.run([LOSETUP, "-d", LOOPDEV], capture_output=True)
        _gadget_rebind(True)
        usb_attached = False
        _release_usb_flock()   # 挂载周期结束才释放, 失败路径继续持锁
        return True, "detached"


def usb_detach_safe():
    try:
        ok, msg = usb_detach()
        print("auto detach:", ok, msg)
    except Exception as e:
        print("auto detach error:", e)


def usb_img_age():
    """车机最后一次写U盘镜像距今的秒数; 读不到返回 -1"""
    try:
        return time.time() - os.path.getmtime(IMG)
    except OSError:
        return -1


# ---------- 风扇温控 (ROCK 3A pwm8 m0) ----------
FAN_CONF = "/etc/default/pwm-fan"
FAN_PWM_GLOB = "/sys/devices/platform/fe6f0000.pwm/pwm/pwmchip*/pwm0"
FAN_DEFAULTS = {"FAN_MODE": "auto", "FAN_MANUAL_DUTY": "50",
                "FAN_CURVE": "45000:0 50000:35 60000:55 70000:80 75000:100",
                "FAN_HYST": "3000", "FAN_PERIOD": "40000", "FAN_POLL": "10"}


def _fan_conf_read():
    d = dict(FAN_DEFAULTS)
    try:
        with open(FAN_CONF) as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith("#") or "=" not in ln:
                    continue
                k, v = ln.split("=", 1)
                d[k.strip()] = v.strip().strip('"')
    except OSError:
        pass
    return d


def _fan_conf_set(updates):
    try:
        with open(FAN_CONF) as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    out, seen = [], set()
    for ln in lines:
        k = ln.split("=", 1)[0].strip() if "=" in ln and not ln.strip().startswith("#") else None
        if k in updates:
            out.append("%s=%s" % (k, updates[k]))
            seen.add(k)
        else:
            out.append(ln)
    for k, v in updates.items():
        if k not in seen:
            out.append("%s=%s" % (k, v))
    tmp = FAN_CONF + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, FAN_CONF)


def fan_state():
    c = _fan_conf_read()
    try:
        manual = max(0, min(100, int(c.get("FAN_MANUAL_DUTY", "50"))))
    except ValueError:
        manual = 50
    st = {"ok": True, "mode": c.get("FAN_MODE", "auto"), "manual": manual,
          "curve": c.get("FAN_CURVE", ""), "present": False, "temp": None, "duty": None}
    pw = sorted(glob.glob(FAN_PWM_GLOB))
    if pw:
        st["present"] = True
        try:
            with open(pw[0] + "/period") as f:
                period = int(f.read().strip() or 0)
            with open(pw[0] + "/duty_cycle") as f:
                duty = int(f.read().strip() or 0)
            st["duty"] = int(round(duty * 100.0 / period)) if period else 0
        except (OSError, ValueError):
            pass
    for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        try:
            with open(z + "/type") as f:
                if f.read().strip() != "cpu-thermal":
                    continue
            with open(z + "/temp") as f:
                st["temp"] = int(f.read().strip()) / 1000.0
            break
        except (OSError, ValueError):
            continue
    return st


def fan_apply(mode, manual):
    if mode not in ("auto", "manual"):
        return False, "模式无效"
    try:
        manual = max(0, min(100, int(manual)))
    except (TypeError, ValueError):
        return False, "转速无效"
    _fan_conf_set({"FAN_MODE": mode, "FAN_MANUAL_DUTY": str(manual)})
    return True, "ok"


# ---------- 网络设置 (netplan -> systemd-networkd) ----------
NETPLAN_FILE = "/etc/netplan/10-dhcp-all-interfaces.yaml"
_net_roll_timer = None
_net_roll_snap = None
_net_lock = threading.Lock()


def _netplan_cfg():
    cfg = {}
    if yaml is not None:
        try:
            with open(NETPLAN_FILE) as f:
                cfg = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            cfg = {}
    net = cfg.setdefault("network", {})
    net.setdefault("version", 2)
    net.setdefault("renderer", "networkd")
    return cfg


def _net_rollback():
    global _net_roll_timer, _net_roll_snap
    with _net_lock:
        snap = _net_roll_snap
        _net_roll_snap = None
        _net_roll_timer = None
        if snap is None:
            return
        try:
            with open(NETPLAN_FILE, "w") as f:
                f.write(snap)
            subprocess.run(["netplan", "apply"], capture_output=True, timeout=60)
            print("net rollback: restored previous netplan config")
        except OSError as ex:
            print("net rollback error:", ex)


def _netplan_apply(cfg):
    """写 netplan 并 apply; 成功后挂 90s 确认回滚, 防止改错地址失联。"""
    global _net_roll_timer, _net_roll_snap
    if yaml is None:
        return False, "应用失败: 缺 python3-yaml"
    with _net_lock:
        try:
            with open(NETPLAN_FILE) as f:
                snap = f.read()
        except OSError:
            snap = None
        tmp = NETPLAN_FILE + ".tmp"
        try:
            with open(tmp, "w") as f:
                f.write(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
            os.chmod(tmp, 0o600)
            os.replace(tmp, NETPLAN_FILE)
            r = subprocess.run(["netplan", "apply"], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as ex:
            return False, "应用失败: %s" % ex
        if r.returncode != 0:
            if snap is not None:
                try:
                    with open(NETPLAN_FILE, "w") as f:
                        f.write(snap)
                    subprocess.run(["netplan", "apply"], capture_output=True, timeout=60)
                except OSError:
                    pass
            return False, (r.stderr or r.stdout).strip()[-200:]
        if snap is not None:
            _net_roll_snap = snap
            if _net_roll_timer:
                _net_roll_timer.cancel()
            _net_roll_timer = threading.Timer(90, _net_rollback)
            _net_roll_timer.daemon = True
            _net_roll_timer.start()
        return True, "ok"


def net_confirm():
    global _net_roll_timer, _net_roll_snap
    with _net_lock:
        had = _net_roll_timer is not None
        if _net_roll_timer:
            _net_roll_timer.cancel()
        _net_roll_timer = None
        _net_roll_snap = None
        return had


def _wifi_iface():
    try:
        for n in sorted(os.listdir("/sys/class/net")):
            if n.startswith("wl"):
                return n
    except OSError:
        pass
    return None


def _ipv4_of(iface):
    try:
        aj = json.loads(subprocess.run(["ip", "-j", "addr", "show", iface],
                                       capture_output=True, text=True, timeout=10).stdout or "[]")
        return [a["local"] + "/" + str(a["prefixlen"])
                for i in aj for a in i.get("addr_info", []) if a.get("family") == "inet"]
    except Exception:
        return []


def net_state():
    st = {"ok": True, "roll_pending": _net_roll_timer is not None, "wired": {}, "wifi": {}}
    net = _netplan_cfg().get("network") or {}
    e = (net.get("ethernets") or {}).get("end0") or {}
    w = st["wired"]
    w["iface"] = "end0"
    w["dhcp"] = bool(e.get("dhcp4", True))
    try:
        with open("/sys/class/net/end0/operstate") as f:
            w["link"] = f.read().strip()
        with open("/sys/class/net/end0/address") as f:
            w["mac"] = f.read().strip()
    except OSError:
        w["link"], w["mac"] = "absent", ""
    w["ipv4"] = _ipv4_of("end0")
    try:
        rj = json.loads(subprocess.run(["ip", "-j", "route", "show", "default"],
                                       capture_output=True, text=True, timeout=10).stdout or "[]")
        w["gw"] = rj[0].get("gateway", "") if rj else ""
    except Exception:
        w["gw"] = ""
    try:
        out = subprocess.run(["resolvectl", "dns", "end0"], capture_output=True, text=True, timeout=10).stdout
        w["dns"] = out.split(":", 1)[-1].split() if ":" in out else []
    except Exception:
        w["dns"] = []
    ad = e.get("addresses") or []
    w["cfg_ip"] = ad[0].split("/")[0] if ad else ""
    w["cfg_prefix"] = ad[0].split("/")[1] if ad and "/" in ad[0] else "24"
    rt = e.get("routes") or []
    w["cfg_gw"] = (rt[0].get("via", "") if rt else "") or e.get("gateway4") or ""
    w["cfg_dns"] = (e.get("nameservers") or {}).get("addresses") or []
    wi = st["wifi"]
    n = _wifi_iface()
    wi["iface"], wi["present"] = n, bool(n)
    wi["ssid"], wi["ipv4"], wi["saved"] = "", [], []
    if n:
        try:
            with open("/sys/class/net/%s/operstate" % n) as f:
                wi["link"] = f.read().strip()
        except OSError:
            wi["link"] = "down"
        try:
            out = subprocess.run(["iw", "dev", n, "link"], capture_output=True, text=True, timeout=10).stdout
            for ln in out.splitlines():
                if ln.strip().startswith("SSID:"):
                    wi["ssid"] = ln.split(":", 1)[1].strip()
        except Exception:
            pass
        wi["ipv4"] = _ipv4_of(n)
        wf = (net.get("wifis") or {}).get(n) or {}
        wi["saved"] = list((wf.get("access-points") or {}).keys())
    st["ap"] = ap_state()
    st["bt"] = bt_state()
    return st


def net_wired_apply(mode, ip, prefix, gw, dns):
    import ipaddress as _ipa
    cfg = _netplan_cfg()
    eth = cfg["network"].setdefault("ethernets", {})
    # 原 Armbian 模板按 e* 匹配统配 DHCP; 改显式 end0 定义, 避免双重匹配冲突
    eth.pop("all-eth-interfaces", None)
    if mode == "dhcp":
        eth["end0"] = {"dhcp4": True, "dhcp6": True, "ipv6-privacy": True}
    elif mode == "static":
        try:
            _ipa.ip_address(ip)
            pfx = int(prefix)
            if not 0 <= pfx <= 32:
                raise ValueError
            g = _ipa.ip_address(gw) if gw else None
            ds = [str(_ipa.ip_address(x)) for x in (dns or []) if x]
        except (ValueError, TypeError):
            return False, "参数无效"
        e = {"dhcp4": False, "dhcp6": True, "addresses": ["%s/%d" % (ip, pfx)]}
        if g:
            e["routes"] = [{"to": "default", "via": str(g)}]
        if ds:
            e["nameservers"] = {"addresses": ds}
        eth["end0"] = e
    else:
        return False, "参数无效"
    return _netplan_apply(cfg)


def net_wifi_apply(ssid, psk):
    if not ssid or len(ssid) > 32:
        return False, "参数无效"
    n = _wifi_iface()
    if not n:
        return False, "未检测到无线网卡"
    cfg = _netplan_cfg()
    wf = cfg["network"].setdefault("wifis", {}).setdefault(n, {"dhcp4": True, "dhcp6": True})
    wf["access-points"] = {ssid: ({"password": psk} if psk else {})}
    return _netplan_apply(cfg)


def net_wifi_forget():
    n = _wifi_iface()
    cfg = _netplan_cfg()
    wfs = (cfg.get("network") or {}).get("wifis") or {}
    if n and n in wfs:
        del wfs[n]
        return _netplan_apply(cfg)
    return True, "ok"


def _ssid_unescape(s):
    # iw 把非 ASCII SSID 输出成 \xHH 转义, 还原成 UTF-8 便于网页显示
    if "\\x" not in s:
        return s
    try:
        raw = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), s)
        return raw.encode("latin-1").decode("utf-8")
    except (UnicodeError, ValueError):
        return s


def net_wifi_scan():
    n = _wifi_iface()
    if not n:
        return False, "未检测到无线网卡", []
    # 未接管时接口可能 DOWN, scan 会报 Network is down; 先拉起 (不关联)
    subprocess.run(["ip", "link", "set", n, "up"], capture_output=True, timeout=10)
    try:
        r = subprocess.run(["iw", "dev", n, "scan"], capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        return False, "应用失败: scan timeout", []
    if r.returncode != 0:
        return False, (r.stderr or "scan failed").strip()[-120:], []
    aps, cur = [], None
    for ln in r.stdout.splitlines():
        s = ln.strip()
        if ln.startswith("BSS "):
            cur = {"ssid": "", "signal": -100, "sec": "开放"}
            aps.append(cur)
        elif cur is not None:
            if s.startswith("SSID:"):
                cur["ssid"] = _ssid_unescape(s[5:].strip())
            elif s.startswith("signal:"):
                try:
                    cur["signal"] = float(s.split()[1])
                except (IndexError, ValueError):
                    pass
            elif s.startswith("RSN:") or s.startswith("WPA:"):
                cur["sec"] = "WPA"
    aps = [a for a in aps if a["ssid"]]
    aps.sort(key=lambda a: -a["signal"])
    seen, out = set(), []
    for a in aps:
        if a["ssid"] in seen:
            continue
        seen.add(a["ssid"])
        out.append(a)
    return True, "ok", out[:20]


# ---------- 个人热点 (hostapd + dnsmasq + NAT) ----------
AP_CONF = "/etc/tsf-ap.conf"
AP_DEFAULTS = {"AP_ENABLE": "0", "AP_SSID": "TeslaSentry", "AP_PSK": "12345678",
               "AP_HW_MODE": "g", "AP_CHANNEL": "6",
               "AP_BAND": "auto", "AP_CH_MODE": "auto", "AP_CH_MANUAL": "6"}
_5G_CH = (36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124,
          128, 132, 136, 140, 144, 149, 153, 157, 161, 165)


def _sta_freq():
    out = subprocess.run(["iw", "dev", "wlp1s0", "link"], capture_output=True, text=True, timeout=10).stdout
    m = re.search(r"freq:\s*(\d+)", out)
    return int(m.group(1)) if m else 0


def _sta_dfs(freq):
    # 内核监管域标记为 radar detection 的信道: 仅 iwlwifi 能在其上做 AP CAC
    try:
        phy = os.path.basename(os.readlink("/sys/class/net/wlp1s0/phy80211"))
        out = subprocess.run(["iw", "phy", phy, "info"], capture_output=True, text=True, timeout=10).stdout
        for ln in out.splitlines():
            if re.match(r"\s*\*\s*%d\.0 MHz" % freq, ln):
                return "radar detection" in ln
    except Exception:
        pass
    return False


def _wifi_driver():
    try:
        return os.path.basename(os.readlink("/sys/class/net/wlp1s0/device/driver"))
    except Exception:
        return ""


def _chan_no_ir(freq):
    # 网卡固件监管(如 Intel self-managed)标 no IR 的信道不能建 AP
    try:
        phy = os.path.basename(os.readlink("/sys/class/net/wlp1s0/phy80211"))
        out = subprocess.run(["iw", "phy", phy, "info"], capture_output=True, text=True, timeout=10).stdout
        for ln in out.splitlines():
            if re.match(r"\s*\*\s*%d\.0 MHz" % freq, ln):
                return "no IR" in ln
    except Exception:
        pass
    return False


def _ap_operstate():
    try:
        with open("/sys/class/net/ap0/operstate") as f:
            return f.read().strip()
    except OSError:
        return ""


def _wired_has_ip():
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", "end0"],
                             capture_output=True, text=True, timeout=10).stdout
        return "inet " in out
    except Exception:
        return False


def _ap_conf():
    d = dict(AP_DEFAULTS)
    try:
        with open(AP_CONF) as f:
            for ln in f:
                ln = ln.strip()
                if ln and not ln.startswith("#") and "=" in ln:
                    k, v = ln.split("=", 1)
                    d[k.strip()] = v.strip()
    except OSError:
        pass
    return d


def _freq_to_channel(freq):
    if freq >= 5000:
        return "a", (freq - 5000) // 5
    if freq >= 2400:
        return "g", (freq - 2407) // 5
    return "g", 6


def ap_state():
    c = _ap_conf()
    st = {"enable": c["AP_ENABLE"] == "1", "mode": c["AP_ENABLE"], "ssid": c["AP_SSID"],
          "psk": c["AP_PSK"], "hw_mode": c["AP_HW_MODE"], "channel": c["AP_CHANNEL"],
          "band": c["AP_BAND"], "ch_mode": c["AP_CH_MODE"], "ch_manual": c["AP_CH_MANUAL"],
          "sta_connected": bool(_sta_freq()), "wired_net": _wired_has_ip(),
          "up": os.path.isdir("/sys/class/net/ap0") and _ap_operstate() == "up", "clients": 0}
    if st["up"]:
        try:
            out = subprocess.run(["iw", "dev", "ap0", "station", "dump"],
                                 capture_output=True, text=True, timeout=10).stdout
            st["clients"] = out.count("Station ")
        except Exception:
            pass
    return st


def ap_apply(enable, ssid, psk, band="auto", ch_mode="auto", ch_manual=0):
    if not ssid or len(ssid) > 32:
        return False, "参数无效"
    mode = enable if isinstance(enable, str) else ("1" if enable else "0")
    mode = mode.strip().lower()
    mode = "1" if mode in ("1", "true", "on") else ("auto" if mode == "auto" else "0")
    if mode != "0" and psk and not 8 <= len(psk) <= 63:
        return False, "参数无效"
    band = band if band in ("auto", "2g", "5g") else "auto"
    ch_mode = ch_mode if ch_mode in ("auto", "manual") else "auto"
    try:
        ch_manual = int(ch_manual or 0)
    except (TypeError, ValueError):
        ch_manual = 0
    c = _ap_conf()
    c["AP_ENABLE"] = mode
    c["AP_SSID"] = ssid
    c["AP_PSK"] = psk or c["AP_PSK"]
    c["AP_BAND"], c["AP_CH_MODE"] = band, ch_mode
    dfs_need = False
    run = mode == "1"
    if mode == "auto":
        # 兜底策略: WiFi 或 有线网 任一可用则关热点, 两者都没有才开
        run = not (bool(_sta_freq()) or _wired_has_ip())
    if run:
        f = _sta_freq()
        if f:
            # 与 STA 并发时硬件要求同信道: 频段/信道自选仅在未连 WiFi 时生效
            sb, sc = _freq_to_channel(f)
            dfs_need = _sta_dfs(f)
            if dfs_need and _wifi_driver() != "iwlwifi":
                return False, "已连WiFi处于雷达信道, 当前网卡不支持AP雷达检测; 请断开WiFi或改连2.4G/5G 149-165"
            if band != "auto" and band != sb:
                return False, "热点须与已连WiFi同频段; 自选请先断开WiFi"
            if ch_mode == "manual" and ch_manual != sc:
                return False, "热点须与已连WiFi同信道; 自选请先断开WiFi"
            hw, ch = sb, sc
        elif ch_mode == "manual":
            if not (1 <= ch_manual <= 13 or ch_manual in (149, 153, 157, 161, 165)):
                return False, "信道无效(2.4G:1-13, 5G:149-165)"
            mb = "2g" if ch_manual <= 13 else "5g"
            if band != "auto" and band != mb:
                return False, "频段与信道不匹配"
            hw, ch = ("g" if mb == "2g" else "a"), ch_manual
        else:
            hw, ch = ("a", 149) if band == "5g" else ("g", 6)
        ap_freq = (5000 + ch * 5) if hw == "a" else (2407 + ch * 5)
        if _chan_no_ir(ap_freq):
            return False, "当前网卡不允许在 %dMHz 建热点(5G 受固件限制); 请改用 2.4G" % ap_freq
        c["AP_HW_MODE"], c["AP_CHANNEL"] = hw, str(ch)
        c["AP_CH_MANUAL"] = str(ch_manual or ch)
    with open(AP_CONF, "w") as f:
        f.write("\n".join("%s=%s" % (k, c[k]) for k in AP_DEFAULTS) + "\n")
    r = subprocess.run(["systemctl", "restart" if run else "stop", "tsf-hotspot.service"],
                       capture_output=True, text=True, timeout=60)
    if run and r.returncode != 0:
        return False, "应用失败: " + (r.stderr or "").strip()[-160:]
    if run:
        time.sleep(2)
        if not os.path.isdir("/sys/class/net/ap0"):
            return False, "应用失败: ap0 未创建"
        deadline = time.time() + (85 if dfs_need else 20)
        while time.time() < deadline:
            if _ap_operstate() == "up":
                return True, "热点设置已应用"
            time.sleep(2)
        return False, "热点未启动: 信道检测未通过或 hostapd 失败"
    return True, "热点设置已应用(当前无需开启)" if mode == "auto" else "热点设置已应用"


# ---------- 蓝牙 (bluez / bluetoothctl) ----------
def _bt(*args, timeout=25):
    try:
        r = subprocess.run(["bluetoothctl"] + list(args), capture_output=True, text=True, timeout=timeout)
        return r.stdout + r.stderr
    except (OSError, subprocess.TimeoutExpired) as ex:
        return "error: %s" % ex


def bt_state():
    st = {"present": os.path.isdir("/sys/class/bluetooth/hci0"), "powered": False,
          "discoverable": False, "name": "", "devices": []}
    if not st["present"]:
        return st
    out = _bt("show")
    for ln in out.splitlines():
        s = ln.strip()
        if s.startswith("Powered:"):
            st["powered"] = s.split(":", 1)[1].strip() == "yes"
        elif s.startswith("Discoverable:"):
            st["discoverable"] = s.split(":", 1)[1].strip() == "yes"
        elif s.startswith("Alias:"):
            st["name"] = s.split(":", 1)[1].strip()
    for ln in _bt("devices").splitlines():
        p = ln.split(None, 2)
        if len(p) >= 2 and p[0] == "Device":
            mac = p[1]
            name = p[2] if len(p) > 2 else mac
            st["devices"].append({"mac": mac, "name": name, "connected": False, "paired": False})
    conn = {l.split()[1] for l in _bt("devices", "Connected").splitlines() if l.startswith("Device")}
    pair = {l.split()[1] for l in _bt("devices", "Paired").splitlines() if l.startswith("Device")}
    for d in st["devices"]:
        d["connected"] = d["mac"] in conn
        d["paired"] = d["mac"] in pair
    return st


def bt_apply(power, discoverable, name):
    if power:
        subprocess.run(["systemctl", "start", "bluetooth.service"], capture_output=True, timeout=30)
        time.sleep(1)
        if os.path.isdir("/sys/class/bluetooth/hci0") and not _bt("list").strip():
            # 开机时固件缺失导致 hci0 setup 失败: 固件就位后重载 btusb 重新初始化
            subprocess.run(["modprobe", "-r", "btusb"], capture_output=True, timeout=30)
            time.sleep(1)
            subprocess.run(["modprobe", "btusb"], capture_output=True, timeout=30)
            time.sleep(3)
            subprocess.run(["systemctl", "restart", "bluetooth.service"], capture_output=True, timeout=30)
            time.sleep(2)
    out = _bt("power", "on" if power else "off")
    if power:
        _bt("discoverable", "on" if discoverable else "off")
        if name:
            _bt("system-alias", name[:32])
    return ("error" not in out.lower()), out.strip()[-160:]


def bt_scan():
    if not os.path.isdir("/sys/class/bluetooth/hci0"):
        return False, "未检测到蓝牙", []
    subprocess.run(["systemctl", "start", "bluetooth.service"], capture_output=True, timeout=30)
    _bt("power", "on")
    _bt("--timeout", "8", "scan", "on", timeout=20)
    devs = []
    for ln in _bt("devices").splitlines():
        p = ln.split(None, 2)
        if len(p) >= 2 and p[0] == "Device":
            devs.append({"mac": p[1], "name": p[2] if len(p) > 2 else p[1]})
    return True, "ok", devs[:20]


def bt_pair(mac):
    if not re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac or ""):
        return False, "参数无效"
    out = _bt("pair", mac, timeout=30)
    _bt("trust", mac)
    out += _bt("connect", mac, timeout=30)
    ok = "Connected: yes" in _bt("info", mac) or "Paired: yes" in _bt("info", mac)
    return ok, out.strip()[-160:]


def bt_remove(mac):
    if not re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac or ""):
        return False, "参数无效"
    _bt("remove", mac)
    return True, "ok"


# ---------- 设备连接与物理存储盘管理 ----------
STORAGE_MNT = "/mnt/tsf-storage"
STORAGE_USE_SCRIPT = "/opt/tesla-sentry/storage-use.sh"
STORAGE_INIT_SCRIPT = "/opt/tesla-sentry/storage-init.sh"


def storage_ready():
    """外接盘路径必须真实挂载; 其它平台沿用原有归档目录语义。"""
    if ARCHIVE == STORAGE_MNT or ARCHIVE.startswith(STORAGE_MNT + "/"):
        return os.path.ismount(STORAGE_MNT)
    return True


def _run_cmd(args, timeout=30):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _current_storage_source():
    if not storage_ready():
        return ""
    try:
        return _run_cmd(["findmnt", "-n", "-T", IMG, "-o", "SOURCE"]).stdout.strip()
    except Exception:
        return ""


def _human_bytes(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    units = ["B", "K", "M", "G", "T"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return ("%.1f" % n).rstrip("0").rstrip(".") + units[i]


def _disk_serial(path):
    try:
        r = _run_cmd(["udevadm", "info", "--query=property", "--name=" + path])
        props = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
        return props.get("ID_SERIAL_SHORT") or props.get("ID_SERIAL") or ""
    except Exception:
        return ""


def _usb_disks():
    try:
        r = _run_cmd(["lsblk", "-b", "-J", "-o", "NAME,PATH,SIZE,TYPE,FSTYPE,MOUNTPOINT,TRAN,MODEL,LABEL"])
        data = json.loads(r.stdout or "{}")
    except Exception:
        return []
    disks = []
    for d in data.get("blockdevices", []):
        if d.get("type") != "disk" or d.get("tran") != "usb":
            continue
        parts = []
        for p in d.get("children") or []:
            if p.get("type") != "part":
                continue
            size_bytes = int(p.get("size") or 0)
            parts.append({"dev": p.get("path") or "/dev/" + p.get("name", ""),
                          "size": _human_bytes(size_bytes), "size_bytes": size_bytes,
                          "fstype": p.get("fstype") or "",
                          "mount": p.get("mountpoint") or "", "label": p.get("label") or ""})
        disk_bytes = int(d.get("size") or 0)
        disk_path = d.get("path") or "/dev/" + d.get("name", "")
        disks.append({"disk": disk_path,
                      "model": (d.get("model") or "").strip(),
                      "size": _human_bytes(disk_bytes), "size_bytes": disk_bytes,
                      "serial": _disk_serial(disk_path),
                      "parts": parts})
    return disks


def _find_usb_part(device):
    for d in _usb_disks():
        for p in d["parts"]:
            if p["dev"] == device:
                return d, p
    return None, None


def _find_usb_disk(device):
    for d in _usb_disks():
        if d["disk"] == device:
            return d
    return None


def _otg_info():
    """读取真实主机连接线索; 不把网页挂载管理状态 usb_attached 当成 OTG 连接"""
    udc = _udc()
    state = speed = ""
    if udc:
        for name, attr in (("state", "state"), ("current_speed", "speed")):
            try:
                with open("/sys/class/udc/%s/%s" % (udc, name)) as f:
                    value = f.read().strip()
                if attr == "state":
                    state = value
                else:
                    speed = value
            except OSError:
                pass
    connected = bool(udc and state in ("configured", "addressed", "suspended")
                     and speed.lower() != "unknown")
    return {"udc": udc or "", "state": state, "speed": speed, "connected": connected}


def storage_status():
    otg = _otg_info()
    try:
        st = os.stat(IMG)
        img_size, img_used = st.st_size, st.st_blocks * 512
    except OSError:
        img_size = img_used = 0
    try:
        with open(os.path.join(GADGET_DIR, "strings/0x409/serialnumber")) as f:
            gadget_serial = f.read().strip()
    except OSError:
        gadget_serial = ""
    try:
        with open(IMG, "rb") as f:
            f.seek(0x64)
            volume_serial = "%08X" % int.from_bytes(f.read(4), "little")
    except OSError:
        volume_serial = ""
    return {"ok": True, "storage_ready": storage_ready(), "storage_mount": STORAGE_MNT,
            "udc": otg["udc"], "state": otg["state"], "speed": otg["speed"],
            "host_connected": otg["connected"], "attached": usb_attached,
            "img": IMG, "img_size": img_size, "img_used": img_used,
            "gadget_serial": gadget_serial, "volume_serial": volume_serial,
            "archive": ARCHIVE, "source": _current_storage_source(), "disks": _usb_disks()}


def storage_format(device, confirm):
    d, p = _find_usb_part(device)
    if not p:
        return False, "只允许格式化 USB 硬盘的分区"
    if _otg_info()["connected"]:
        return False, "OTG 仍连接主机, 请先拔出电脑/车机数据线再格式化"
    expected = d.get("serial") or os.path.basename(d["disk"])
    if not confirm or confirm != expected:
        return False, "序列号不匹配, 请输入页面显示的序列号"
    if _current_storage_source() == device:
        return False, "当前使用中的存储盘不能格式化"
    try:
        if p.get("mount"):
            r = _run_cmd(["umount", device])
            if r.returncode != 0:
                return False, "卸载失败: " + r.stderr.strip()[-120:]
        r = _run_cmd(["mkfs.ext4", "-F", device], timeout=180)
        if r.returncode != 0:
            return False, "格式化失败: " + (r.stderr or r.stdout).strip()[-200:]
        return True, "已格式化为 ext4"
    except Exception as e:
        return False, str(e)


def storage_use(device):
    d, p = _find_usb_part(device)
    if not p:
        return False, "只允许使用 USB 硬盘的分区"
    if _current_storage_source() == device:
        return True, "already"
    if p.get("fstype") != "ext4":
        return False, "请先把该分区格式化为 ext4"
    if usb_attached:
        ok, msg = usb_detach()
        if not ok:
            return False, msg
    try:
        r = _run_cmd(["sh", STORAGE_USE_SCRIPT, device], timeout=1800)
    except Exception as e:
        return False, str(e)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip()[-300:]
    # 归档路径是运行时常量, 延迟重启本查看器让新路径生效, 同时保证当前响应先返回
    subprocess.Popen(["sh", "-c", "sleep 1; systemctl restart sentry-viewer.service"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True, "switched"


def storage_init(device, percent, confirm):
    d = _find_usb_disk(device)
    if not d:
        return False, "只允许初始化 USB 硬盘"
    if _otg_info()["connected"]:
        return False, "OTG 仍连接主机, 请先拔出电脑/车机数据线再初始化"
    expected = d.get("serial") or os.path.basename(d["disk"])
    if not confirm or confirm != expected:
        return False, "序列号不匹配, 请输入页面显示的序列号"
    try:
        percent = int(percent)
    except (TypeError, ValueError):
        return False, "虚拟U盘比例无效"
    if percent < 10 or percent > 90:
        return False, "虚拟U盘比例需在 10% - 90% 之间"
    total = int(d.get("size_bytes") or 0)
    gib = 1024 ** 3
    virtual_gb = int(total * percent / 100 // gib)
    archive_gb = int(total // gib) - virtual_gb
    if virtual_gb < 4 or archive_gb < 4:
        return False, "分区太小, 虚拟盘和归档区都至少需要 4G"
    try:
        r = _run_cmd(["sh", STORAGE_INIT_SCRIPT, device, str(virtual_gb), str(archive_gb)], timeout=1800)
    except Exception as e:
        return False, str(e)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip()[-300:]
    subprocess.Popen(["sh", "-c", "sleep 1; systemctl restart sentry-viewer.service"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True, "initialized:%d:%d" % (virtual_gb, archive_gb)


# ---------- 车机U盘「幽灵占用」回收 (位图自愈) ----------
# 深检发现: exFAT 分配位图里会积累「已标记占用、但没有任何目录项引用」的簇 ——
# 缩容/中断写入时代的残留 + 偶发的删除残留。车机和网页据此把死数据当真实占用,
# 容量被幽灵数据慢慢吃掉 (实测曾达 4.5GB), 却没有任何入口能清掉。
# 修法与 Windows chkdsk 同款: 空闲窗口内按规范重走目录树, 收集全部被引用的簇,
# 把位图里未被引用的簇清零 (同簇的 FAT 陈旧项一并归零)。目录项一个不碰。
# 安全窗口与归档同步同款: 车机 10 分钟没写 + 跨进程排他锁 + 短暂停止 USB 导出。
# 默认关闭: 该逻辑尚未完成离线回归, 不该在自动维护循环里改写车机镜像。
# 需要在已有设备上手动启用时, 在启动环境里显式设 TSF_RECLAIM_MIN_MB=1024 等正值。
RECLAIM_MIN_MB = int(os.environ.get("TSF_RECLAIM_MIN_MB", "0"))       # 0=关闭; >0 时才动手
RECLAIM_IDLE_S = int(os.environ.get("TSF_RECLAIM_IDLE_S", "600"))    # 与 tesla-sync.sh 的空闲门槛一致
RECLAIM_EVERY_S = 4 * 3600                                            # 两次回收至少间隔 4 小时
_reclaim_ts = [0.0]


def _exf_collect_refs(fd):
    """只读按 exFAT 规范走一遍目录树。
    返回 (引用簇集合, 位图簇链, FAT 数组, 几何 dict)。
    任何结构异常直接抛出 —— 调用方放弃本次操作, 绝不带着疑问写盘。"""
    vbr = os.pread(fd, 512, 0)
    if len(vbr) < 512 or vbr[3:11] != b"EXFAT   ":
        raise ValueError("bad VBR")
    g = {
        "bps": 1 << vbr[108],
        "spc": 1 << vbr[109],
        "fat_off": struct.unpack_from("<I", vbr, 80)[0],
        "fat_len": struct.unpack_from("<I", vbr, 84)[0],
        "heap_off": struct.unpack_from("<I", vbr, 88)[0],
        "cl_cnt": struct.unpack_from("<I", vbr, 92)[0],
        "root_cl": struct.unpack_from("<I", vbr, 96)[0],
    }
    g["csz"] = g["bps"] * g["spc"]
    g["cl_max"] = g["cl_cnt"] + 2
    fat_raw = os.pread(fd, g["fat_len"] * g["bps"], g["fat_off"] * g["bps"])
    if len(fat_raw) < g["fat_len"] * g["bps"]:
        raise ValueError("short FAT")
    fat = struct.unpack("<%dI" % (len(fat_raw) // 4), fat_raw)

    def rd_cl(c):
        if c < 2 or c >= g["cl_max"]:
            raise ValueError("cluster out of range: %d" % c)
        d = os.pread(fd, g["csz"], (g["heap_off"] + (c - 2) * g["spc"]) * g["bps"])
        if len(d) < g["csz"]:
            raise ValueError("short cluster read")
        return d

    def chain(c):
        out, seen = [], set()
        while 2 <= c < g["cl_max"]:
            if c in seen:
                raise ValueError("FAT loop at %d" % c)
            seen.add(c)
            out.append(c)
            nxt = fat[c]
            if nxt >= 0xFFFFFFF7:
                return out
            if nxt < 2:
                raise ValueError("broken chain at %d" % c)
            c = nxt
        raise ValueError("chain out of range")

    refs = set()

    def add_entry(clusters):
        for c in clusters:
            if not (2 <= c < g["cl_max"]):
                raise ValueError("ref cluster out of range: %d" % c)
        refs.update(clusters)

    def walk_dir(cl, nochain, size, depth):
        """遍历一个目录: 记录自身占用 + 解析里面的文件/子目录"""
        if depth > 8:
            raise ValueError("dir nesting too deep")
        if nochain:
            n = max(1, (size + g["csz"] - 1) // g["csz"])
            if cl + n > g["cl_max"]:
                raise ValueError("no-chain dir beyond volume")
            cls = list(range(cl, cl + n))
        else:
            cls = chain(cl)
        add_entry(cls)
        data = b"".join(rd_cl(c) for c in cls)
        i = 0
        while i + 32 <= len(data):
            t = data[i]
            if t == 0:
                break
            if t in (0x81, 0x82, 0x83):     # 位图/大小写表/卷标只在根目录出现, 单项即完
                i += 32
                continue
            if t == 0x85:                    # 活着的文件/目录项集
                nsec = data[i + 1]
                end = i + 32 * (1 + nsec)
                if nsec < 2 or end > len(data):
                    raise ValueError("bad entry set")
                raw = data[i:end]
                attrs = struct.unpack_from("<H", raw, 4)[0]
                fc, dl, noch = 0, 0, False
                for j in range(nsec):
                    sec = raw[32 * (1 + j):32 * (2 + j)]
                    st = sec[0]
                    if st == 0xC0:
                        noch = bool(sec[1] & 0x02)
                        fc = struct.unpack_from("<I", sec, 20)[0]
                        dl = struct.unpack_from("<Q", sec, 24)[0]
                    elif st == 0xC1:
                        pass                # 名字内容不影响簇引用
                if attrs & 0x10:            # 子目录
                    walk_dir(fc, noch, dl, depth + 1)
                else:                       # 文件
                    n = (dl + g["csz"] - 1) // g["csz"]
                    if fc and n:
                        if noch:
                            if fc + n > g["cl_max"]:
                                raise ValueError("no-chain file beyond volume")
                            add_entry(range(fc, fc + n))
                        else:
                            add_entry(chain(fc))
                i = end
            else:
                i += 32                     # 死项/未知项: 车机自己的删除标记, 不碰
    # 根目录单独走一遍: 先抽出位图/大小写表两个元数据文件的簇链
    root_cls = chain(g["root_cl"])
    add_entry(root_cls)
    root_data = b"".join(rd_cl(c) for c in root_cls)
    bm_cls = up_cls = None
    i = 0
    while i + 32 <= len(root_data):
        t = root_data[i]
        if t == 0:
            break
        if t in (0x81, 0x82):
            cl = struct.unpack_from("<I", root_data, i + 20)[0]
            if t == 0x81:
                bm_cls = cl
            else:
                up_cls = cl
            i += 32
            continue
        if t == 0x83:
            i += 32
            continue
        if t == 0x85:
            nsec = root_data[i + 1]
            end = i + 32 * (1 + nsec)
            if nsec < 2 or end > len(root_data):
                raise ValueError("bad root entry set")
            raw = root_data[i:end]
            attrs = struct.unpack_from("<H", raw, 4)[0]
            fc, dl, noch = 0, 0, False
            for j in range(nsec):
                sec = raw[32 * (1 + j):32 * (2 + j)]
                st = sec[0]
                if st == 0xC0:
                    noch = bool(sec[1] & 0x02)
                    fc = struct.unpack_from("<I", sec, 20)[0]
                    dl = struct.unpack_from("<Q", sec, 24)[0]
            if attrs & 0x10:
                walk_dir(fc, noch, dl, 1)
            else:
                n = (dl + g["csz"] - 1) // g["csz"]
                if fc and n:
                    if noch:
                        if fc + n > g["cl_max"]:
                            raise ValueError("no-chain file beyond volume")
                        add_entry(range(fc, fc + n))
                    else:
                        add_entry(chain(fc))
            i = end
        else:
            i += 32
    if bm_cls is None or up_cls is None:
        raise ValueError("root missing bitmap/upcase entry")
    bm_chain = chain(bm_cls)
    up_chain = chain(up_cls)
    refs.update(bm_chain)
    refs.update(up_chain)
    return refs, bm_chain, fat, g


def _exf_bitmap_bytes(fd, bm_chain, g):
    data = b"".join(os.pread(fd, g["csz"], (g["heap_off"] + (c - 2) * g["spc"]) * g["bps"])
                    for c in bm_chain)
    if len(data) < len(bm_chain) * g["csz"]:
        raise ValueError("short bitmap read")
    return data


def _exf_orphan_count(bm_data, refs, g):
    """位图标记了、但目录树没引用的簇数"""
    n = 0
    cl_max = g["cl_max"]
    for c in range(2, cl_max):
        if (bm_data[(c - 2) >> 3] >> ((c - 2) & 7)) & 1 and c not in refs:
            n += 1
    return n


def reclaim_ghost_allocations():
    """回收位图里的幽灵占用。返回释放的字节数 (0 = 本次没动手)。"""
    if RECLAIM_MIN_MB <= 0 or not os.path.exists(IMG):
        return 0
    now = time.time()
    if now - _reclaim_ts[0] < RECLAIM_EVERY_S:
        return 0
    # 网页正在管理U盘(镜像已挂载)时不掺和; 车机最近还在写时不动刀
    if os.path.ismount(MNT):
        return 0
    if usb_img_age() < RECLAIM_IDLE_S:
        return 0
    # 第一遍: 不打扰车机的只读探查, 先量出幽灵量够不够门槛
    try:
        fd = os.open(IMG, os.O_RDONLY)
        try:
            refs, bm_chain, fat, g = _exf_collect_refs(fd)
            bm_data = _exf_bitmap_bytes(fd, bm_chain, g)
            ghosts = _exf_orphan_count(bm_data, refs, g)
        finally:
            os.close(fd)
    except Exception as e:
        print("reclaim probe skip:", e)
        return 0
    if ghosts * g["csz"] < RECLAIM_MIN_MB * 1048576:
        return 0
    # 够门槛: 走与归档同步同款的安全窗口 (进程内互斥 + 跨进程排他锁 + 停止导出)
    _reclaim_ts[0] = now
    with usb_lock:
        if os.path.ismount(MNT):
            return 0
        for _ in range(6):
            if _acquire_usb_flock():
                break
            time.sleep(0.4)
        else:
            print("reclaim skip: usb busy (web/archive/selfheal)")
            return 0
        try:
            if not _gadget_rebind(False):   # 停止导出, 车机几秒内看不到U盘
                print("reclaim skip: gadget unbind failed")
                return 0
            time.sleep(1)
            fd = os.open(IMG, os.O_RDWR)
            try:
                # 停止导出后状态已稳定: 以这一遍的结果为准 (避免用探查时的旧账)
                refs, bm_chain, fat, g = _exf_collect_refs(fd)
                bm_data = _exf_bitmap_bytes(fd, bm_chain, g)
                ghosts = _exf_orphan_count(bm_data, refs, g)
                if ghosts * g["csz"] < RECLAIM_MIN_MB * 1048576:
                    return 0
                # 1) 重写分配位图: 引用簇置位, 其余清零
                nbytes = (g["cl_cnt"] + 7) // 8
                if nbytes > len(bm_chain) * g["csz"]:
                    raise ValueError("bitmap region too small")
                new_bm = bytearray(nbytes)
                for c in refs:
                    new_bm[(c - 2) >> 3] |= 1 << ((c - 2) & 7)
                # 2) 清掉被释放簇上的 FAT 陈旧项, 让 FAT 与位图一致
                cl_max = g["cl_max"]
                dirty = [c for c in range(2, cl_max)
                         if fat[c] != 0 and c not in refs]
                fat_out = None
                if dirty:
                    for c in dirty:
                        fat[c] = 0
                    fat_out = struct.pack("<%dI" % len(fat), *fat)
                # 内容全部在内存备好后再落盘 (避免写一半失败留下半新半旧的位图)
                off = 0
                for c in bm_chain:
                    os.pwrite(fd, bytes(new_bm[off:off + g["csz"]]),
                              (g["heap_off"] + (c - 2) * g["spc"]) * g["bps"])
                    off += g["csz"]
                if fat_out:
                    os.pwrite(fd, fat_out, g["fat_off"] * g["bps"])
                os.fsync(fd)
                print("reclaim: freed %d clusters (%.2f GB), fat cleaned %d"
                      % (ghosts, ghosts * g["csz"] / 1073741824, len(dirty)))
                return ghosts * g["csz"]
            finally:
                os.close(fd)
        except Exception as e:
            print("reclaim error (no write?):", e)
            return 0
        finally:
            _gadget_rebind(True)            # 无论成败都恢复导出
            time.sleep(1)
            _release_usb_flock()



def live_latest():
    """归档里最新的 RecentClips 片段组与其入库时间 (秒); 没有返回 ("", 0)。
    片段由 tesla-live-sync.py 在后台持续只读同步进归档 (不打断车机), 延时约 1~2 分钟。"""
    base = os.path.join(ARCHIVE, "RecentClips")
    try:
        cands = sorted((n for n in os.listdir(base)
                        if re.match(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$", n)
                        and os.path.isdir(os.path.join(base, n))), reverse=True)
    except OSError:
        return "", 0.0
    if not cands:
        return "", 0.0
    newest = 0.0
    try:
        for f in os.listdir(os.path.join(base, cands[0])):
            newest = max(newest, os.path.getmtime(os.path.join(base, cands[0], f)))
    except OSError:
        pass
    return cands[0], newest


def usb_real(p):
    """校验镜像内相对路径, 返回挂载点下真实绝对路径或 None"""
    p = (p or "").strip().strip("/")
    if not p:
        return MNT
    rp = os.path.realpath(os.path.join(MNT, p))
    if rp != MNT and not rp.startswith(MNT + "/"):
        return None
    return rp


# ---------- 文件管理器: 批量操作 (多选删除/移动/复制/重命名) ----------
# 清空 TeslaCam 时保留这几个直属目录, 车机继续录制时会直接往里写
FM_KEEP_ROOTS = ("RecentClips", "SavedClips", "SentryClips")


def _fm_name(s):
    """重命名用的安全文件名: 允许中文, 禁止路径分隔符与控制字符"""
    s = (s or "").strip()
    if not s or len(s) > 120 or s in (".", ".."):
        return None
    if "/" in s or "\\" in s or "\x00" in s or any(ord(c) < 32 for c in s):
        return None
    return s


def _fm_root(area):
    """返回该区域根目录的真实绝对路径; 区域不可用返回 None"""
    if area == "usb":
        if not usb_attached or not os.path.ismount(MNT):
            return None
        return os.path.realpath(MNT)
    if area == "archive":
        return os.path.realpath(ARCHIVE)
    return None


def _fm_resolve(area, p, root, must_exist=True):
    """把前端传来的路径解析为 root 内的真实绝对路径; 越界/根目录/不存在返回 None"""
    if area == "usb":
        rp = usb_real((p or "").strip().strip("/"))
        rp = os.path.realpath(rp) if rp else None
    else:
        q = _map_archive((p or "").strip())
        if not q.startswith(ARCHIVE):
            return None
        rp = os.path.realpath(q)
    if not rp or rp == root or not rp.startswith(root + "/"):
        return None
    if must_exist and not os.path.lexists(rp):
        return None
    return rp


def _fm_dest_dir(area, p, root):
    """移动/复制的目标目录, 允许根目录本身; 不存在或越界返回 None"""
    if area == "usb":
        rp = usb_real((p or "").strip().strip("/"))
        rp = os.path.realpath(rp) if rp else None
    else:
        q = _map_archive((p or "").strip())
        if not q.startswith(ARCHIVE):
            return None
        rp = os.path.realpath(q)
    if not rp or (rp != root and not rp.startswith(root + "/")) or not os.path.isdir(rp):
        return None
    return rp


def _fm_purge_teslacam(root):
    """清空 TeslaCam 内全部录像, 保留 TeslaCam 与三个标准直属目录, 不动其他根目录"""
    base = usb_real("TeslaCam")
    base = os.path.realpath(base) if base else None
    if not base or not base.startswith(root + "/") or not os.path.isdir(base):
        return False, "TeslaCam 目录不存在", 0, [], {}
    stat = {"n": 0, "freed": 0}

    def walk(d, top=False):
        try:
            entries = os.listdir(d)
        except OSError:
            return
        for e in entries:
            p = os.path.join(d, e)
            try:
                if os.path.isdir(p) and not os.path.islink(p):
                    walk(p)
                    if not (top and e in FM_KEEP_ROOTS):
                        try:
                            os.rmdir(p)
                        except OSError:
                            pass
                else:
                    sz = os.path.getsize(p)
                    os.remove(p)
                    stat["n"] += 1
                    stat["freed"] += sz
            except OSError:
                pass

    walk(base, top=True)
    subprocess.run(["sync"], capture_output=True)
    freed = stat["freed"]
    if freed >= 1073741824:
        sz = "%.2f GB" % (freed / 1073741824.0)
    elif freed >= 1048576:
        sz = "%.1f MB" % (freed / 1048576.0)
    else:
        sz = "%.1f KB" % (freed / 1024.0)
    msg = "已清空 TeslaCam: 删除 %d 个文件, 释放 %s (其他根目录未改动)" % (stat["n"], sz)
    return True, msg, stat["n"], [], {"freed": freed}


def fm_action(area, op, items, dest, name):
    """文件管理器批量操作入口, 返回 (ok, msg, done, failed, extra)"""
    root = _fm_root(area)
    if not root:
        return False, ("车机U盘未连接, 请先点「连接车机U盘」" if area == "usb" else "区域参数错误"), 0, [], {}
    if op == "purge_teslacam":
        if area != "usb":
            return False, "清空 TeslaCam 仅在车机U盘区域可用", 0, [], {}
        return _fm_purge_teslacam(root)
    if not isinstance(items, list) or not items:
        return False, "没有选中任何文件", 0, [], {}
    if len(items) > 200:
        return False, "单次最多操作 200 项", 0, [], {}

    srcs = []
    for it in items:
        rp = _fm_resolve(area, str(it), root)
        if not rp:
            return False, "路径无效或不存在: %s" % it, 0, [], {}
        srcs.append(rp)
    # 父目录先于子项处理时子项会消失, 按深度降序删更稳
    srcs.sort(key=lambda x: x.count(os.sep), reverse=True)
    done, failed = 0, []

    def fail(s, why):
        failed.append(os.path.basename(s) + ": " + why)

    def finish(msg):
        if area == "usb":
            subprocess.run(["sync"], capture_output=True)
        tail = (", %d 项失败" % len(failed)) if failed else ""
        return done > 0, msg + tail, done, failed, {}

    if op == "delete":
        for s in srcs:
            try:
                if os.path.isdir(s) and not os.path.islink(s):
                    shutil.rmtree(s)
                else:
                    os.remove(s)
                done += 1
            except FileNotFoundError:
                done += 1
            except OSError as ex:
                fail(s, ex.strerror or str(ex))
        return finish("已删除 %d 项" % done)

    if op == "rename":
        if len(srcs) != 1:
            return False, "重命名只能选中一项", 0, [], {}
        nn = _fm_name(name)
        if not nn:
            return False, "新名称无效", 0, [], {}
        s = srcs[0]
        d = os.path.join(os.path.dirname(s), nn)
        if os.path.lexists(d):
            return False, "目标名称已存在: " + nn, 0, [], {}
        try:
            os.rename(s, d)
            done = 1
            return finish("已重命名为 " + nn)
        except OSError as ex:
            return False, "重命名失败: " + (ex.strerror or str(ex)), 0, [], {}

    if op in ("move", "copy"):
        dd = _fm_dest_dir(area, dest, root)
        if not dd:
            return False, "目标目录不存在或不在允许范围内", 0, [], {}
        verb = "移动" if op == "move" else "复制"
        for s in srcs:
            d = os.path.join(dd, os.path.basename(s))
            if os.path.lexists(d):
                fail(s, "目标已存在")
                continue
            if os.path.isdir(s) and (d == s or d.startswith(s + "/")):
                fail(s, "不能%s到自身内部" % verb)
                continue
            try:
                if op == "move":
                    shutil.move(s, d)
                elif os.path.isdir(s):
                    shutil.copytree(s, d, symlinks=True)
                else:
                    shutil.copy2(s, d)
                done += 1
            except (OSError, shutil.Error) as ex:
                fail(s, str(ex)[-80:])
        return finish("已%s %d 项" % (verb, done))

    return False, "未知操作: %s" % op, 0, [], {}


def _range_bounds(hdr, size):
    """解析 Range 头, 返回 (start, end) / None(整体) / 'BAD'(格式错) / 'UNSAT'(越界)
    iOS/Safari 的下载器会先发 bytes=-N (取尾部) 探一下 moov, 必须支持,
    否则连接会被直接掐断, 手机端只会存到前一小段 (表现为"下载下来只有 1 秒")。"""
    if not hdr:
        return None
    m = re.match(r"bytes=(\d*)-(\d*)$", (hdr or "").strip())
    if not m:
        return "BAD"
    a, b = m.group(1), m.group(2)
    if a == "" and b == "":
        return "BAD"
    if a == "":                       # bytes=-N: 最后 N 字节
        n = int(b)
        if n <= 0 or size <= 0:
            return "UNSAT"
        return (max(0, size - n), size - 1)
    start = int(a)
    if start >= size:
        return "UNSAT"
    end = int(b) if b else size - 1
    if end < start:
        return "UNSAT"
    return (start, min(end, size - 1))


def serve_file(self, fp, head_only=False):
    """流式发送文件 (支持 Range / HEAD), 用于下载"""
    fn = os.path.basename(fp)
    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
    ct = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp",
          "css": "text/css", "html": "text/html", "htm": "text/html", "txt": "text/plain",
          "json": "application/json", "pdf": "application/pdf", "svg": "image/svg+xml",
          "mp4": "video/mp4", "mp3": "audio/mpeg", "wav": "audio/wav"}.get(ext, "application/octet-stream")
    try:
        size = os.path.getsize(fp)
    except OSError:
        self._send(404, b"not found")
        return
    rb = _range_bounds(self.headers.get("Range"), size)
    if rb in ("BAD", "UNSAT"):
        self.send_response(416 if rb == "UNSAT" else 400)
        if rb == "UNSAT":
            self.send_header("Content-Range", "bytes */%d" % size)
        self.send_header("Content-Length", "0")
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        return
    if rb:
        start, end = rb
    else:
        start, end = 0, size - 1
    length = max(0, end - start + 1)
    self.send_response(206 if rb else 200)
    self.send_header("Content-Type", ct)
    self.send_header("Content-Length", str(length))
    self.send_header("Accept-Ranges", "bytes")
    self.send_header("Content-Disposition", 'attachment; filename="%s"' % urllib.parse.quote(fn))
    if rb:
        self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
    self.end_headers()
    if head_only:
        return
    with open(fp, "rb") as f:
        f.seek(start)
        remain = length
        while remain > 0:
            chunk = f.read(min(65536, remain))
            if not chunk:
                break
            try:
                self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                return
            remain -= len(chunk)


LIVE_SCRIPT = "tesla-live-sync.py"
LIVE_LOG = "/root/tesla-live.log"
LIVE_STATE = "/root/.tesla-live-state.json"


def _proc_running(needle):
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as f:
                    if needle.encode() in f.read():
                        return True
            except Exception:
                continue
    except Exception:
        pass
    return False


_ARC_SIZE_CACHE = {"t": 0.0, "v": 0}

_BITCOUNT = bytes(bin(i).count("1") for i in range(256))
_IMG_USED_CACHE = {"t": 0.0, "path": "", "v": None}


def _exfat_used(path):
    """exFAT 镜像里「实际写入」了多少字节 = 已分配簇 × 簇大小。

    镜像文件是预分配的 (st_blocks ≈ 标称容量), 用宿主盘上的占用来画进度条会一直是
    100%, 所以这里读卷内 Allocation Bitmap (根目录里 type=0x81 的目录项) 数已用簇。
    位图只覆盖簇堆, 通常几十~几百 KB, 读一次几毫秒。失败返回 None 交给上层兜底。
    """
    now = time.time()
    if _IMG_USED_CACHE["v"] is not None and _IMG_USED_CACHE["path"] == path \
            and now - _IMG_USED_CACHE["t"] < 60:
        return _IMG_USED_CACHE["v"]
    v = None
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY)
        vbr = os.pread(fd, 512, 0)
        if len(vbr) >= 512 and vbr[3:11] == b"EXFAT   ":
            bps = 1 << vbr[108]
            csize = bps << vbr[109]
            heap = struct.unpack_from("<I", vbr, 88)[0] * bps
            ccnt = struct.unpack_from("<I", vbr, 92)[0]
            root = struct.unpack_from("<I", vbr, 96)[0]
            fat_off = struct.unpack_from("<I", vbr, 80)[0]
            fat_len = struct.unpack_from("<I", vbr, 84)[0]
            nfats = vbr[110]
            flags = struct.unpack_from("<H", vbr, 106)[0]
            fat_at = (fat_off + (fat_len if (nfats > 1 and (flags & 0x1)) else 0)) * bps
            hi = ccnt + 2

            def nextc(c):
                e = os.pread(fd, 4, fat_at + c * 4)
                return struct.unpack("<I", e)[0] if len(e) == 4 else 0xFFFFFFFF

            # 根目录簇链里找 Allocation Bitmap 目录项
            bm_cl = bm_len = 0
            c, guard = root, 0
            while 2 <= c < hi and guard < 8192 and not bm_cl:
                buf = os.pread(fd, csize, heap + (c - 2) * csize)
                if not buf:
                    break
                for i in range(0, len(buf) - 31, 32):
                    et = buf[i]
                    if et == 0x00:
                        break
                    if et == 0x81:
                        bm_cl = struct.unpack_from("<I", buf, i + 20)[0]
                        bm_len = struct.unpack_from("<Q", buf, i + 24)[0]
                        break
                c = nextc(c)
                guard += 1
                if c >= 0xFFFFFFF7:
                    break
            if bm_cl:
                need = min((ccnt + 7) // 8, bm_len or (ccnt + 7) // 8)
                got, c, guard = 0, bm_cl, 0
                used = 0
                while got < need and 2 <= c < hi and guard < 65536:
                    n = min(csize, need - got)
                    buf = os.pread(fd, n, heap + (c - 2) * csize)
                    if not buf:
                        break
                    for b in buf:
                        used += _BITCOUNT[b]
                    got += len(buf)
                    c = nextc(c)
                    guard += 1
                    if c >= 0xFFFFFFF7:
                        break
                if got:
                    v = used * csize
    except Exception:
        v = None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
    # 只在成功时缓存, 解析失败下次再试 (可能是镜像还没建好)
    if v is not None:
        _IMG_USED_CACHE.update(t=now, path=path, v=v)
    return v



def archive_size():
    """归档区实际占用。os.walk 在文件多的时候要几十~几百毫秒, 而存储卡每 10 秒轮询一次,
    所以做 60 秒缓存, 别让面板把设备拖慢。"""
    now = time.time()
    if _ARC_SIZE_CACHE["t"] and now - _ARC_SIZE_CACHE["t"] < 60:
        return _ARC_SIZE_CACHE["v"]
    sz = _dir_size(ARCHIVE) if os.path.isdir(ARCHIVE) else 0
    _ARC_SIZE_CACHE.update(t=now, v=sz)
    return sz


_SYS_CACHE = {"t": 0.0, "v": {}}


def sys_status():
    """系统状态一行: CPU 温度 / CPU 占用 / 内存占用 (给存储卡折叠区显示)。

    存储卡每 10 秒轮询一次, 可能多个端同时打开 —— 结果缓存 3 秒;
    CPU 占用必须两次采样 /proc/stat 求差, 睡 150ms 就当是采样窗口。"""
    now = time.time()
    if _SYS_CACHE["t"] and now - _SYS_CACHE["t"] < 3:
        return _SYS_CACHE["v"]
    d = {"cpu_temp": None, "cpu_pct": None, "mem_total": 0, "mem_used": 0}
    # CPU 温度: thermal_zone 里取读数合理的热区最大值 (SoC 通常只有一两个)
    temps = []
    for i in range(8):
        try:
            with open("/sys/class/thermal/thermal_zone%d/temp" % i) as f:
                v = int(f.read().strip())
        except (OSError, ValueError):
            continue
        if 20000 < v < 150000:            # 20~150°C 之外当它是坏传感器
            temps.append(v / 1000.0)
    if temps:
        d["cpu_temp"] = round(max(temps), 1)
    # CPU 占用: /proc/stat 两次采样求差 (user+nice+system+idle+... 与 idle+ iowait)
    def _cpu_pair():
        with open("/proc/stat") as f:
            vals = [int(x) for x in f.readline().split()[1:] if x.isdigit()]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return sum(vals), idle
    try:
        t1, i1 = _cpu_pair()
        time.sleep(0.15)
        t2, i2 = _cpu_pair()
        dt = t2 - t1
        if dt > 0:
            d["cpu_pct"] = round(max(0.0, min(100.0, (dt - (i2 - i1)) / dt * 100)), 1)
    except Exception:
        pass
    # 内存: MemTotal - MemAvailable (MemAvailable 才是内核估计的真正可用量)
    try:
        mi = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                mi[k] = int(v.strip().split()[0]) * 1024
        d["mem_total"] = mi.get("MemTotal", 0)
        avail = mi.get("MemAvailable", mi.get("MemFree", 0))
        d["mem_used"] = max(0, mi.get("MemTotal", 0) - avail)
    except Exception:
        pass
    _SYS_CACHE.update(t=now, v=d)
    return d


def disk_usage():
    """存储卡三行数据: 虚拟U盘(卷内已写入) / 归档区 / 整盘总占用

    三者口径不同, 不能相加:
      虚拟U盘 = 镜像内部已分配空间 / 镜像标称容量 (镜像文件在宿主盘上是整份预分配的,
                用宿主占用来画会永远是 100%)
      归档区  = 盒子上的历史副本 / 用户分配的归档额度 (未设额度时=副本+宿主盘剩余)
      总占用  = 整块宿主盘已用 / 容量"""
    d = {}
    # 虚拟U盘: 稀疏镜像文件在宿主盘上的真实占用; 标称容量另给 (两者通常不等)
    try:
        im = os.stat(IMG)
        d["img_nominal"] = im.st_size
        d["img_real"] = getattr(im, "st_blocks", 0) * 512
    except OSError:
        d["img_nominal"] = d["img_real"] = 0
    # 虚拟U盘「已写入」: 挂载时直接读 exFAT 的 statvfs (含文件系统开销, 最准),
    # 没挂载时按 Allocation Bitmap 数已分配簇; 都失败才退回宿主盘实占
    d["img_used"] = None
    if os.path.ismount(MNT):
        try:
            st = os.statvfs(MNT)
            if st.f_blocks > 0:
                d["img_used"] = (st.f_blocks - st.f_bavail) * st.f_frsize
        except OSError:
            pass
    if d["img_used"] is None:
        d["img_used"] = _exfat_used(IMG)
    d["arc_used"] = archive_size()
    # 整盘 = 镜像文件所在分区 (镜像和归档同一块盘)
    d["disk_total"] = d["disk_used"] = d["disk_free"] = 0
    for p in (os.path.dirname(IMG) or "/", ARCHIVE):
        try:
            hf = os.statvfs(p)
        except OSError:
            continue
        if hf.f_blocks <= 0:
            continue
        fr = hf.f_frsize
        d["disk_total"] = hf.f_blocks * fr
        d["disk_free"] = hf.f_bavail * fr
        # bavail 扣除了 root 保留块; 用 bfree 统计真实数据/元数据占用,
        # 避免新格式化的 ext4 盘凭空显示约 5% 已用
        d["disk_used"] = (hf.f_blocks - hf.f_bfree) * fr
        d["disk_reserved"] = (hf.f_bfree - hf.f_bavail) * fr
        break
    # 归档额度实时拉取: 同盘时 = 整盘格式化容量 - 虚拟U盘镜像标称容量,
    # 与初始化时的分配口径一致。BOX_MAX_GB 只是清理策略上限, 不是用户分配额度,
    # 不能拿它冒充归档容量显示。
    arc_quota = _archive_quota()
    d["arc_total"] = arc_quota or d["arc_used"] + d["disk_free"]
    d["arc_free"] = (min(d["disk_free"], max(0, arc_quota - d["arc_used"]))
                     if arc_quota else d["disk_free"])
    # 兼容旧字段: 挂载时 = 车载U盘 (exFAT) 内部用量, 否则 = 整盘
    d["src"], d["used"], d["total"] = "loop", d["disk_used"], d["disk_total"]
    for p, usb in ((MNT, True), (ARCHIVE, False)):
        if usb and not os.path.ismount(MNT):
            # MNT 目录本身常驻 (tmpfs), 未挂载镜像时 statvfs 会读到 tmpfs 的
            # 小容量 (如 0.7G), 必须跳过
            continue
        try:
            st = os.statvfs(p)
        except OSError:
            continue
        if st.f_blocks <= 0:
            continue
        fr = st.f_frsize
        d["src"] = "usb" if usb else "loop"
        d["used"] = (st.f_blocks - st.f_bavail) * fr
        d["total"] = st.f_blocks * fr
        break
    if d["disk_total"] <= 0 and d["arc_used"] <= 0:
        return None
    return d


def live_status():
    """车机在线只读同步的健康状态 (给页面显示心跳)"""
    running = _proc_running(LIVE_SCRIPT)
    pending = 0
    try:
        with open(LIVE_STATE) as f:
            pending = len(json.load(f).get("__pending__", {}))
    except Exception:
        pass
    ago, last = None, ""
    try:
        st = os.stat(LIVE_LOG)
        ago = int(time.time() - st.st_mtime)
        with open(LIVE_LOG, "rb") as f:
            f.seek(max(0, st.st_size - 2048))
            lines = [l for l in f.read().decode("utf-8", "replace").splitlines() if l.strip()]
        for line in reversed(lines):
            if "已同步" in line:
                last = line.split("] ", 1)[-1]
                break
        if not last and lines:
            last = lines[-1].split("] ", 1)[-1]
    except Exception:
        pass
    return {"running": running, "pending": pending, "ago": ago, "last": last,
            "disk": disk_usage(), "sys": sys_status()}


def active_skin():
    ap = os.path.join(SKIN_DIR, "active.json")
    try:
        with open(ap) as f:
            return json.load(f).get("skin")
    except Exception:
        return None


# ---------------- 多路合成导出 (ffmpeg) ----------------
FFMPEG_BIN = os.environ.get("TSF_FFMPEG") or "ffmpeg"
FFPROBE_BIN = os.environ.get("TSF_FFPROBE") or "ffprobe"
STITCH_DIR = os.environ.get("TSF_CACHE", "/opt/tesla-sentry/cache") + "/stitch-tmp"  # 不用 /tmp: tmpfs 占内存, 大视频会挤爆 RAM
STITCH_JOBS = {}
STITCH_LOCK = threading.Lock()
# 视频流并发上限: 事件多的时候浏览器会一口气请求上百个预览, 不限流会拖死设备
MEDIA_SEM = threading.BoundedSemaphore(int(os.environ.get("TSF_MEDIA_CONN", "16")))  # 媒体流并发上限: 4路视频+封面+接口要同时走, 太小会让新请求排队
MEDIA_ACTIVE = [0]        # 正在推送的视频流数量: 自动升级要等它归零, 别打断正在看的人
# 播放器会话: 前端打开播放器后定时心跳, 退出/关页立即 leave。
# 完整转码作业绑定会话; 会话消失即取消, 避免退出后后台继续吃 CPU。
PLAYBACK_SESSIONS = {}
PLAYBACK_LOCK = threading.Lock()
PLAYBACK_TTL = 30
THUMB_DIR = os.environ.get("TSF_CACHE", "/opt/tesla-sentry/cache") + "/thumbs"
THUMB_SEM = threading.BoundedSemaphore(2)
THUMB_W = 400


def thumb_file(fp, ss_t=1.0):
    """抽指定秒数那一帧并缓存在 eMMC, 返回 jpg 路径; 抽不出来返回 None。
    列表缩略图 (/thumb) 和飞书推送封面共用。"""
    try:
        st = os.stat(fp)
    except OSError:
        return None
    key = hashlib.md5(("%s|%d|%d|%g" % (fp, st.st_size, int(st.st_mtime), ss_t)).encode()).hexdigest()
    out = os.path.join(THUMB_DIR, key + ".jpg")
    try:                               # 0 字节是上次 ffmpeg 失败留下的残骸, 视为无效缓存
        if os.path.getsize(out) == 0:
            os.remove(out)
    except OSError:
        pass
    if os.path.isfile(out):
        return out
    try:
        os.makedirs(THUMB_DIR, exist_ok=True)
    except OSError:
        pass
    tmp = os.path.join(THUMB_DIR, "%s.%d.tmp.jpg" % (key, threading.get_ident()))
    if not THUMB_SEM.acquire(timeout=12):
        return None
    try:
        if os.path.isfile(out):
            return out
        # 指定秒数可能落在片段末尾之外(触发帧偏移略超时长), 逐级回落
        for ss in ("%.1f" % ss_t, "1", "0"):
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
                subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
                                "-ss", ss, "-i", fp, "-frames:v", "1",
                                "-vf", "scale=%d:-2" % THUMB_W, "-q:v", "7", tmp],
                               capture_output=True, timeout=30)
                if os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
                    os.replace(tmp, out)
                    return out
            except Exception:
                pass
        return None
    finally:
        THUMB_SEM.release()
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
# ---------- 在线清晰度: 按需转码 + eMMC 缓存 (设备端单任务串行, 防止重转码打崩内核) ----------
# 源 1280x960 (4:3); 用固定目标码率: 公网 5G 上行只有 ~120KB/s, CRF 模式码率不可控会传不完
# 8 核 T760 实测: -threads 8 + superfast 比 2 线程快一倍 (20s->10s/分钟片段), 内存峰值充足 (720p 后仍余 ~980MB)
RES_SCALE = {"360p": (480, 360, 600), "480p": (640, 480, 500), "720p": (960, 720, 900)}  # 宽,高,kbps
# 编码参数版本号: 参与缓存 key。v3: 远程默认 360p15, rkvdec+FFmpeg 混合转码; 其它档先降帧再缩放。
RES_ENC_VER = "3"
RES_DIR = os.environ.get("TSF_CACHE", "/opt/tesla-sentry/cache") + "/res-cache"
# 10 秒预缓冲单独放系统盘, 体积小、可让外接盘空闲待机; 完整转码缓存仍走 RES_DIR。
PREVIEW_DIR = os.environ.get("TSF_PREVIEW_CACHE", "/opt/tesla-sentry/preview-cache")
PREVIEW_MAX = 512 * 1024 * 1024
PREVIEW_TTL = 3 * 86400       # 预缓冲保留 3 天; 源视频被删则立即清对应缓存
VPU_TRANSCODE = os.environ.get("TSF_VPU_TRANSCODE", "/opt/tesla-sentry/tsf-vpu-transcode.sh")
# 目录延迟到 ensure_dirs() 且确认外接盘已挂载后创建, 避免模块加载时写入系统盘。
Q_SEM = threading.BoundedSemaphore(int(os.environ.get("TSF_TR_CODES", "2")))  # 并发转码上限: 8核允许2个×4线程, 多路点开排队时间减半
USER_TRANS = [0]      # 正在排队/占用转码槽的用户请求数; 后台预热看到 >0 就让位
RES_MAX = 2 * 1024 * 1024 * 1024  # 清晰度缓存总量上限 2GB, 超了从最旧开始删


def res_cleanup():
    try:
        now = time.time()
        for f in os.listdir(RES_DIR):  # 清理残留转码临时文件 (进程被杀会留下 0 字节 tmp)
            if f.endswith(".tmp") and now - os.path.getmtime(os.path.join(RES_DIR, f)) > 1800:
                try:
                    os.unlink(os.path.join(RES_DIR, f))
                except OSError:
                    pass
        files = [os.path.join(RES_DIR, f) for f in os.listdir(RES_DIR)
                 if f.endswith(".mp4")]
        total = sum(os.path.getsize(f) for f in files if os.path.isfile(f))
        if total <= RES_MAX:
            return
        files.sort(key=lambda f: os.path.getmtime(f))
        for f in files:
            if total <= RES_MAX:
                break
            sz = os.path.getsize(f)
            os.unlink(f)
            total -= sz
    except Exception:
        pass


def preview_cleanup():
    """系统盘预缓冲: 源视频删除/超过3天/超容量时清理, 同时清残留 tmp。"""
    try:
        now = time.time()
        for f in os.listdir(PREVIEW_DIR):
            p = os.path.join(PREVIEW_DIR, f)
            if f.endswith(".tmp") and now - os.path.getmtime(p) > 1800:
                try:
                    os.unlink(p)
                except OSError:
                    pass
        files = []
        for f in os.listdir(PREVIEW_DIR):
            if not f.endswith(".mp4"):
                continue
            p = os.path.join(PREVIEW_DIR, f)
            src_file = p + ".src"
            try:
                with open(src_file, "r", encoding="utf-8") as sf:
                    src = sf.read().strip()
            except OSError:
                src = ""
            try:
                age = now - os.path.getmtime(p)
            except OSError:
                continue
            if age > PREVIEW_TTL or (src and not os.path.isfile(src)):
                try:
                    os.unlink(p)
                    os.unlink(src_file)
                except OSError:
                    pass
                continue
            if os.path.isfile(p):
                files.append(p)
        total = sum(os.path.getsize(f) for f in files)
        if total <= PREVIEW_MAX:
            return
        files.sort(key=lambda f: os.path.getmtime(f))
        for f in files:
            if total <= PREVIEW_MAX:
                break
            sz = os.path.getsize(f)
            try:
                os.unlink(f)
                os.unlink(f + ".src")
            except OSError:
                pass
            total -= sz
    except Exception:
        pass


# ---------- 归档滚动窗口 + 磁盘空间兜底 ----------
# 车机 U 盘里的 RecentClips 本身就是"滚动缓冲": 只留最近约 1 小时, 更旧的由车机自己覆盖。
# 但盒子这边过去是每来一段就抄一份、永久留着, 而哨兵开着时车整夜不睡, 4 路约 140MB/分钟
# (8.4GB/小时), 一晚上就能吃掉几十 GB —— 这才是盒子镜像被撑爆的真正原因。
# 现在让盒子副本按同样窗口滚动: 只留最近 ROLL_MIN 分钟, 更旧的从盒子归档里删掉。
# 车机 U 盘那份完全不碰 (同步脚本只读 U 盘, 靠 exFAT 解析器读, 从不删源文件);
# SentryClips / SavedClips 属于哨兵事件 + 用户主动保存的录像, 由下方 BOX_KEEP_DAYS /
# BOX_MAX_GB 定期清理管理 (只删盒子归档副本, 车机 U 盘那份同样不碰)。
RECENT_ROLL_MIN = int(os.environ.get("TSF_RECENT_ROLL_MIN", "60"))    # 归档滚动窗口(分钟), 0=关闭滚动
FREE_MIN_MB = int(os.environ.get("TSF_FREE_MIN_MB", "4096"))          # 剩余低于此值开始兜底清理
FREE_TARGET_MB = int(os.environ.get("TSF_FREE_TARGET_MB", "10240"))   # 兜底清理到恢复到该值为止
RECENT_KEEP_MIN = int(os.environ.get("TSF_RECENT_KEEP_MIN", "60"))    # 兜底清理时最近 N 分钟必留
# 盒子侧 SentryClips / SavedClips 定期清理 (方案B):
# 哨兵开着时 4 路约 8.4GB/小时, 哨兵事件 + 手动保存的录像只增不删, 盘迟早被吃满。
# 车机 U 盘那份永远不碰, 这里只清盒子归档副本。两个维度独立生效:
#   1) 按天数: 只保留最新事件往前 N 天内的归档 (锚点是最新事件而不是当前时间,
#      停车几天没新事件不会被误清空);
#   2) 按体积: 单个分类超过 MAX_GB 就从最旧的开始删, 直到回到上限以内。
#      teslacam.img 高水位约 170G, loop 盘 207.7G, 盒子归档预算约 12G/类比较安全。
# 同步进行中的目录 (1 小时内有改动) 跳过, 非时间戳命名的目录一律不动。
# 清掉的分类/事件会记入 /archive/.pruned 墓碑文件, 同步端读到就跳过 —— 否则车机 U 盘上
# 还留着的旧事件会被当成新片段重抄回来, 形成 删除→重抄 的死循环 (和 RecentClips 同理)。
BOX_KEEP_DAYS = int(os.environ.get("TSF_BOX_KEEP_DAYS", "14"))        # 盒子侧哨兵/手动保存保留天数, 0=不按天数清
BOX_MAX_GB = int(os.environ.get("TSF_BOX_MAX_GB", "12"))              # 盒子侧单个分类体积上限(GB), 0=不按体积清
# 容量滚动策略 (默认主策略): 归档剩余低于分配额度的 MIN_PCT% 时, 从最旧的已归档
# 事件开始删, 删到剩余 >= TARGET_PCT% 为止 (留回差避免反复触发)。额度实时拉取,
# 阈值可在 conf 里改, 不写死。只删盒子归档副本, 车机 U 盘那份永远不碰。
ARC_FREE_MIN_PCT = float(os.environ.get("TSF_ARC_FREE_MIN_PCT", "10"))
ARC_FREE_TARGET_PCT = float(os.environ.get("TSF_ARC_FREE_TARGET_PCT", "15"))
PRUNED_FILE = os.path.join(ARCHIVE, ".pruned")                        # 墓碑: 每行 "分类/事件名", 同步端跳过


def _archive_quota():
    """归档分配额度实时拉取: 镜像与归档同盘时 = 整盘格式化容量 - 虚拟U盘镜像标称容量。
    与初始化分配口径一致; 不同盘或取不到时返回 0 (调用方自行回退)。"""
    try:
        if os.stat(IMG).st_dev != os.stat(ARCHIVE).st_dev:
            return 0
        hf = os.statvfs(os.path.dirname(IMG) or "/")
        if hf.f_blocks <= 0:
            return 0
        return max(0, hf.f_blocks * hf.f_frsize - os.stat(IMG).st_size)
    except OSError:
        return 0


def free_mb(p):
    try:
        st = os.statvfs(p)
        return st.f_bavail * st.f_frsize // 1048576
    except OSError:
        return -1


def _ev_dt(name):
    """事件目录名就是片段起始时间 (2026-11-05_08-00-23)。
    用文件名里的车机时间来比较, 不受盒子时区设错的影响"""
    try:
        return datetime.datetime.strptime(name[:19], "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return None


def roll_recent():
    """盒子侧 RecentClips 按滚动窗口自动淘汰 (只删盒子归档, 不碰车机 U 盘)"""
    rd = os.path.join(ARCHIVE, "RecentClips")
    if RECENT_ROLL_MIN <= 0 or not os.path.isdir(rd):
        return 0
    evs = []
    for e in os.listdir(rd):
        dt = _ev_dt(e)
        if dt:                       # 非时间戳命名的目录一律不动
            evs.append((dt, e))
    if len(evs) < 2:
        return 0
    evs.sort()
    # 以"最新片段"为锚点而不是当前时间: 车休眠/哨兵关闭期间没有新片段, 就不会被误清空
    cutoff = evs[-1][0] - datetime.timedelta(minutes=RECENT_ROLL_MIN)
    n = 0
    for dt, e in evs:
        if dt < cutoff:
            shutil.rmtree(os.path.join(rd, e), ignore_errors=True)
            n += 1
    return n


def _dir_size(p):
    sz = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                sz += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return sz


def _tombstone(cat, ev):
    """记录已清理的事件, 同步端读到就跳过, 防止 删除→重抄 死循环"""
    try:
        with open(PRUNED_FILE, "a", encoding="utf-8") as f:
            f.write("%s/%s\n" % (cat, ev))
    except OSError:
        pass


def roll_box():
    """盒子侧 SentryClips / SavedClips 定期清理 (按天数 + 按体积), 只删盒子归档, 不碰车机 U 盘"""
    n = 0
    for cat in ("SentryClips", "SavedClips"):
        base = os.path.join(ARCHIVE, cat)
        if not os.path.isdir(base):
            continue
        evs = []
        for e in os.listdir(base):
            dt = _ev_dt(e)
            if dt:                       # 非时间戳命名的目录一律不动
                evs.append((dt, e))
        if not evs:
            continue
        evs.sort()
        # 目录统计 (1 小时内有改动的跳过: 可能还在同步写入)
        sized = []
        for dt, e in evs:
            p = os.path.join(base, e)
            try:
                if time.time() - os.path.getmtime(p) < 3600:
                    continue
                sized.append((dt, e, p, _dir_size(p)))
            except OSError:
                continue
        # 1) 按天数: 锚点 = 该分类最新事件, 只留最近 BOX_KEEP_DAYS 天
        if BOX_KEEP_DAYS > 0:
            cutoff = evs[-1][0] - datetime.timedelta(days=BOX_KEEP_DAYS)
            for dt, e, p, _sz in sized:
                if dt < cutoff and os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                    if not os.path.isdir(p):
                        _tombstone(cat, e)
                        n += 1
        # 2) 按体积: 超出 BOX_MAX_GB 从最旧开始删
        if BOX_MAX_GB > 0:
            left = [(dt, e, p, sz) for dt, e, p, sz in sized if os.path.isdir(p)]
            left.sort()
            total = sum(sz for _, _, _, sz in left)
            budget = BOX_MAX_GB * (1 << 30)
            for dt, e, p, sz in left:
                if total <= budget:
                    break
                shutil.rmtree(p, ignore_errors=True)
                total -= sz
                if not os.path.isdir(p):
                    _tombstone(cat, e)
                    n += 1
    return n


def roll_archive_capacity():
    """容量滚动: 归档剩余 < 额度的 ARC_FREE_MIN_PCT% 时, 跨分类按事件时间从最旧
    开始删, 删到剩余 >= ARC_FREE_TARGET_PCT%。额度/阈值全部实时取, 不写死。
    只删盒子归档副本; 1 小时内有改动的目录 (可能还在同步) 跳过。"""
    quota = _archive_quota()
    if quota <= 0 or ARC_FREE_MIN_PCT <= 0:
        return 0
    used = archive_size()
    if (quota - used) * 100.0 / quota >= ARC_FREE_MIN_PCT:
        return 0
    evs = []
    for cat in ("SentryClips", "SavedClips"):
        base = os.path.join(ARCHIVE, cat)
        if not os.path.isdir(base):
            continue
        for e in os.listdir(base):
            dt = _ev_dt(e)
            if not dt:
                continue
            p = os.path.join(base, e)
            try:
                if time.time() - os.path.getmtime(p) < 3600:
                    continue
                evs.append((dt, cat, e, p, _dir_size(p)))
            except OSError:
                continue
    evs.sort()
    n = 0
    for dt, cat, e, p, sz in evs:
        if (quota - used) * 100.0 / quota >= ARC_FREE_TARGET_PCT:
            break
        shutil.rmtree(p, ignore_errors=True)
        if not os.path.isdir(p):
            _tombstone(cat, e)
            used = max(0, used - sz)
            _ARC_SIZE_CACHE["t"] = 0      # 让存储卡尽快看到新占用
            n += 1
    if n:
        print("[archive] 容量滚动清理 %d 个最旧事件 (剩余 %.1f%%)" % (
            n, (quota - used) * 100.0 / quota), flush=True)
    return n


def health_logger():
    """每分钟记一条 内存/负载/ffmpeg 进程数 到持久日志 (环形, 最多 2000 行)。
    内核 lockup 重启会把 dmesg 清空, 这里是唯一能复盘"死前发生了什么"的证据。"""
    fp = "/opt/tesla-sentry/health.log"
    while True:
        try:
            mem = load = "?"
            with open("/proc/meminfo", encoding="ascii") as f:
                for ln in f:
                    if ln.startswith("MemAvailable"):
                        mem = "%dMB" % (int(ln.split()[1]) // 1024)
                        break
            with open("/proc/loadavg", encoding="ascii") as f:
                load = " ".join(f.read().split()[:3])
            ff = 0
            try:
                for pid in os.listdir("/proc"):
                    if not pid.isdigit():
                        continue
                    try:
                        with open("/proc/%s/comm" % pid, encoding="ascii") as f:
                            if f.read().strip() == "ffmpeg":
                                ff += 1
                    except OSError:
                        continue
            except OSError:
                pass
            with open(fp, "a", encoding="utf-8") as f:
                f.write("%s mem=%s load=%s ffmpeg=%d\n" % (
                    time.strftime("%m-%d %H:%M"), mem, load, ff))
            if os.path.getsize(fp) > 300 * 1024:      # 环形截断, 只留最近 ~2000 行
                try:
                    with open(fp, encoding="utf-8") as f:
                        tail = f.readlines()[-2000:]
                    with open(fp, "w", encoding="utf-8") as f:
                        f.writelines(tail)
                except OSError:
                    pass
        except Exception:
            pass
        time.sleep(60)


def disk_guard():
    rd = os.path.join(ARCHIVE, "RecentClips")
    while True:
        if not storage_ready():
            time.sleep(30)
            continue
        try:
            roll_recent()
        except Exception:
            pass
        try:   # 盒子侧哨兵/手动保存归档定期清理 (方案B)
            roll_box()
        except Exception:
            pass
        try:   # 容量滚动: 归档剩余低于阈值时淘汰最旧事件 (默认主策略)
            roll_archive_capacity()
        except Exception:
            pass
        try:   # 车机U盘幽灵占用回收 (位图自愈, 空闲窗口内才动手)
            reclaim_ghost_allocations()
        except Exception:
            pass
        try:   # 兜底: 万一别的数据把盘吃满, 再按空间淘汰最旧的
            if free_mb(ARCHIVE) < FREE_MIN_MB and os.path.isdir(rd):
                cutoff = time.time() - RECENT_KEEP_MIN * 60
                for e in sorted(os.listdir(rd)):   # 目录名即时间戳, 天然按时间排序
                    if free_mb(ARCHIVE) >= FREE_TARGET_MB:
                        break
                    p = os.path.join(rd, e)
                    try:
                        if not os.path.isdir(p) or os.path.getmtime(p) > cutoff:
                            continue
                    except OSError:
                        continue
                    shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass
        time.sleep(300)


# ---------- 飞书推送: 哨兵触发时把信息和触发画面推到群里 ----------
# 机器人 webhook 只能发文字卡片; 要带封面图必须配「自建应用」的 app_id/app_secret
# (应用需开机器人能力 + im:message/im:resource 权限), 由本程序换取 token 上传图片拿 img_key。
NOTIFY_CONF = os.environ.get("TSF_NOTIFY_CONF", "/opt/tesla-sentry/notify.json")
NOTIFY_STATE = os.environ.get("TSF_NOTIFY_STATE", "/opt/tesla-sentry/notify-state.json")
FEISHU_API = "https://open.feishu.cn/open-apis"
_NC_DEFAULT = {
    "enabled": False, "mode": "dm", "webhook": "", "app_id": "", "app_secret": "",
    "receive_id": "", "receive_id_type": "", "public_url": "", "saved": False, "delay": 20,
    "media": "thumb", "quality": "480p", "vdur": 30,
}
_TOK = {"v": "", "exp": 0}
CAM_NUM = {0: "前视", 3: "左B柱", 4: "右B柱", 5: "左翼子板", 6: "右翼子板", 7: "后视"}
CAM_SUFFIX = {0: "front", 3: "left_pillar", 4: "right_pillar",
              5: "left_repeater", 6: "right_repeater", 7: "back"}
REASON_DETAIL = {
    "sentry_aware_object_detection": "侦测到物体移动",
    "sentry_aware_accel": "侦测到碰撞/震动",
    "sentry_aware_door": "车门被拉动",
    "sentry_aware_handle": "门把手被拉动",
    "sentry_panic": "遭遇袭击 (紧急报警)",
    "sentry_trigger": "哨兵模式触发",
    "user_interaction_honk": "按喇叭保存",
    "user_interaction_dashcam_saved": "手动保存",
    "user_interaction_dashcam_menu": "行车记录仪菜单保存",
}


def notify_conf():
    c = dict(_NC_DEFAULT)
    try:
        with open(NOTIFY_CONF, encoding="utf-8") as f:
            j = json.load(f)
        if isinstance(j, dict):
            c.update(j)
    except Exception:
        pass
    return c


def notify_save(patch):
    c = notify_conf()
    for k, v in (patch or {}).items():
        if k in _NC_DEFAULT:
            c[k] = v
    try:
        os.makedirs(os.path.dirname(NOTIFY_CONF) or ".", exist_ok=True)
        tmp = NOTIFY_CONF + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
        try:
            os.chmod(tmp, 0o600)          # 里面存着 app_secret, 只给 root 读
        except OSError:
            pass
        os.replace(tmp, NOTIFY_CONF)
    except OSError:
        pass
    return c


def _nstate_load():
    try:
        with open(NOTIFY_STATE, encoding="utf-8") as f:
            j = json.load(f)
        return j if isinstance(j, dict) else {}
    except Exception:
        return {}


def _nstate_save(st):
    try:
        os.makedirs(os.path.dirname(NOTIFY_STATE) or ".", exist_ok=True)
        tmp = NOTIFY_STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        os.replace(tmp, NOTIFY_STATE)
    except OSError:
        pass


def _reason_info(reason):
    """reason → (分类, 卡片主题色, 详情)"""
    r = str(reason or "")
    detail = REASON_DETAIL.get(r) or ("未标注原因" if not r else r)
    if r.startswith(("sentry_panic", "sentry_aware_accel")):
        return "遭遇袭击", "red", detail
    if r.startswith(("sentry_aware_door", "sentry_aware_handle")):
        return "车门拉动", "orange", detail
    if r.startswith("sentry_"):
        return "哨兵警觉", "blue", detail
    if r.startswith("user_interaction"):
        return "手动保存", "grey", detail
    return "其他事件", "grey", detail


def _ev_files(d):
    try:
        return sorted(f for f in os.listdir(d) if f.lower().endswith(".mp4"))
    except OSError:
        return []


def _pick_clip(cat, name):
    """按 event.json 的 camera + timestamp 找出触发摄像头那一路的 mp4, 返回 (文件路径, 触发偏移秒, meta);
    对不上时回落到前视。找不到任何片段返回 (None, 0, meta)。"""
    d = os.path.join(ARCHIVE, cat, name)
    meta = {}
    try:
        with open(os.path.join(d, "event.json"), encoding="utf-8", errors="ignore") as f:
            meta = json.load(f) or {}
    except Exception:
        meta = {}
    files = _ev_files(d)
    if not files:
        return None, 0.0, meta
    cam_key = CAM_SUFFIX.get(int(meta.get("camera")) if str(meta.get("camera", "")).strip().isdigit() else -1)
    ts = None
    try:
        ts = datetime.datetime.strptime(str(meta.get("timestamp"))[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        ts = None
    if ts is not None:
        for f in files:                       # 文件名前 19 位是片段开始时间, 与 timestamp 同一时基
            try:
                s = datetime.datetime.strptime(f[:19], "%Y-%m-%d_%H-%M-%S")
            except ValueError:
                continue
            off = (ts - s).total_seconds()
            if 0 <= off <= 70 and f.rsplit("-", 1)[-1][:-4] == cam_key:
                return os.path.join(d, f), max(0.0, min(off, 60.0)), meta
    front = [f for f in files if f.endswith("-front.mp4")]
    return os.path.join(d, front[0] if front else files[0]), 1.0, meta


def _trigger_frame(cat, name):
    """触发摄像头那一帧的封面图; 返回 (jpg 路径, meta)"""
    fp, off, meta = _pick_clip(cat, name)
    if not fp:
        return None, meta
    return thumb_file(fp, off), meta


def _post_json(url, payload, timeout=12, headers=None):
    """POST JSON 并解析返回。
    注意: 这里用 http.client 而不是 urllib — urllib 会给请求带上 Connection: close,
    飞书网关对这种短连接 POST 会直接断链 (SSL BAD_RECORD_MAC), 实测 http.client 正常。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    h = {"Content-Type": "application/json; charset=utf-8"}
    if headers:
        h.update(headers)
    return json.loads(_http_post(url, body, h, timeout).decode("utf-8", "replace"))


def _tls12():
    """给飞书 API 用的 SSLContext: 强制 TLS 1.2。
    实测国内移动网络下 TLS 1.3 偶发丢/坏记录 (SSLV3_ALERT_BAD_RECORD_MAC),
    同一请求降到 TLS 1.2 后稳定, 所以对飞书固定用 1.2。"""
    global _TLS_CTX
    if _TLS_CTX is None:
        c = ssl.create_default_context()
        try:
            c.maximum_version = ssl.TLSVersion.TLSv1_2
        except Exception:
            pass
        _TLS_CTX = c
    return _TLS_CTX


_TLS_CTX = None


def _http_post(url, body, headers=None, timeout=12):
    """发一个 POST, 返回响应体 bytes; HTTP 4xx/5xx 也照常返回内容 (里面有飞书的错误码)
    TLS 抖动会自动重试 3 次 (每次新建连接)。"""
    u = urllib.parse.urlsplit(url)
    last = None
    for attempt in range(3):
        conn = None
        try:
            if u.scheme == "https":
                conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=timeout,
                                                   context=_tls12())
            elif u.scheme == "http":
                conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
            else:
                raise RuntimeError("不支持的地址: %s" % url[:40])
            path = (u.path or "/") + (("?" + u.query) if u.query else "")
            conn.request("POST", path, body=body, headers=dict(headers or {}))
            r = conn.getresponse()
            return r.read() or b"{}"
        except (ssl.SSLError, ConnectionError, OSError) as ex:
            last = ex
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
    raise last if last else RuntimeError("POST 失败")


def _feishu_token(conf):
    if _TOK["v"] and _TOK["exp"] > time.time() + 60:
        return _TOK["v"]
    j = _post_json(FEISHU_API + "/auth/v3/tenant_access_token/internal",
                   {"app_id": conf.get("app_id", ""), "app_secret": conf.get("app_secret", "")})
    if j.get("code") != 0 or not j.get("tenant_access_token"):
        raise RuntimeError("取 token 失败: %s" % (j.get("msg") or j))
    _TOK["v"] = j["tenant_access_token"]
    _TOK["exp"] = time.time() + max(600, int(j.get("expire") or 7200) - 300)
    return _TOK["v"]


def _feishu_upload(conf, jpg):
    """上传封面图, 返回 image_key (失败抛异常)"""
    with open(jpg, "rb") as f:
        data = f.read()
    bd = "----tsf%s" % hashlib.md5(("%s%.6f" % (jpg, time.time())).encode()).hexdigest()
    pre = ("--%s\r\nContent-Disposition: form-data; name=\"image_type\"\r\n\r\nmessage\r\n"
           "--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"cover.jpg\"\r\n"
           "Content-Type: image/jpeg\r\n\r\n" % (bd, bd)).encode()
    body = pre + data + ("\r\n--%s--\r\n" % bd).encode()
    raw = _http_post(FEISHU_API + "/im/v1/images", body, {
        "Authorization": "Bearer " + _feishu_token(conf),
        "Content-Type": "multipart/form-data; boundary=" + bd,
    }, timeout=30)
    j = json.loads(raw.decode("utf-8", "replace"))
    key = ((j or {}).get("data") or {}).get("image_key")
    if j.get("code") != 0 or not key:
        raise RuntimeError("上传封面失败: %s" % (j.get("msg") or j))
    return key


VID_Q = {"720p": (720, 1500), "480p": (480, 800), "360p": (360, 500)}   # 输出高度, 目标码率 kbps

FONT_DIR = os.environ.get("TSF_FONTS") or "/opt/tesla-sentry/fonts"
FONT_EXTS = (".ttf", ".otf", ".ttc")
# 字体兜底搜索: 有的盒子把中文字体装在系统目录里, 只要找得到就能烧水印,
# 不必非得放在我们的 FONT_DIR (install.sh 那步失败过很多次, 用户直接覆盖 py 升级也不会带字体)
FONT_ALTS = (
    "/usr/share/fonts", "/usr/lib/fonts", "/usr/local/share/fonts",
    "/opt/usr/share/fonts", "/system/fonts", "/opt/etc/fonts",
)
FONT_NAME = "NotoSansSC.ttf"
FONT_SRC = (
    "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf",
    "https://gcore.jsdelivr.net/gh/google/fonts@main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf",
    "https://fastly.jsdelivr.net/gh/google/fonts@main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf",
    "https://ghfast.top/https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf",
    "https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf",
)
FONT_MIN = 2 * 1024 * 1024          # 有效的中文字体至少几 MB, 小于这个说明下到的是错误页
_FONT_CACHE = {"at": 0.0, "path": ""}
FONT_LOCK = threading.Lock()


def _font_cands(dirp, depth=1):
    """列出目录里 (最多 depth 层) 所有可能是字体的文件"""
    if not dirp or not os.path.isdir(dirp):
        return
    base = dirp.rstrip("/").count("/")
    try:
        for root, dirs, files in os.walk(dirp):
            if root.rstrip("/").count("/") - base >= depth:
                dirs[:] = []
            for n in sorted(files):
                if n.lower().endswith(FONT_EXTS):
                    fp = os.path.join(root, n)
                    try:
                        if os.path.getsize(fp) >= 20000:
                            yield fp
                    except OSError:
                        pass
    except OSError:
        return


def _font_has_cjk(fp, chars=(0x4E2D, 0x8F66, 0x5239)):   # 中 / 车 / 刹
    """查 cmap 里有没有这几个常用汉字。
    系统字体目录里常有纯拉丁字体, 拿它烧中文只会得到一排方块, 比没有还难看。"""
    try:
        with open(fp, "rb") as f:
            d = f.read(24 * 1024 * 1024)
        if len(d) < 12:
            return False
        base = 0
        if d[:4] == b"ttcf":                 # 字体集合 (.ttc): 表目录在第一个 face 的偏移处
            if len(d) < 16:
                return False
            base = struct.unpack(">I", d[12:16])[0]
            if base + 12 > len(d):
                return False
        numt = struct.unpack(">H", d[base + 4:base + 6])[0]
        cmap = 0
        for i in range(min(numt, 128)):
            o = base + 12 + i * 16
            if d[o:o + 4] == b"cmap":
                cmap = struct.unpack(">I", d[o + 8:o + 12])[0]
                break
        if not cmap or cmap + 4 > len(d):
            return False
        nsub = struct.unpack(">H", d[cmap + 2:cmap + 4])[0]
        best = 0
        for i in range(min(nsub, 32)):
            o = cmap + 4 + i * 8
            plat, enc, off = struct.unpack(">HHI", d[o:o + 8])
            if plat == 3 and enc in (1, 10):
                best = cmap + off
                break
            if plat == 0 and not best:
                best = cmap + off
        if not best or best + 4 > len(d):
            return False
        fmt = struct.unpack(">H", d[best:best + 2])[0]

        def has(cp):
            try:
                if fmt == 4:
                    segx2 = struct.unpack(">H", d[best + 6:best + 8])[0]
                    seg = segx2 // 2
                    ends = struct.unpack(">%dH" % seg, d[best + 14:best + 14 + segx2])
                    starts = struct.unpack(">%dH" % seg, d[best + 16 + segx2:best + 16 + segx2 * 2])
                    for k in range(seg):
                        if starts[k] <= cp <= ends[k]:
                            return True
                    return False
                if fmt == 12:
                    ng = struct.unpack(">I", d[best + 12:best + 16])[0]
                    for k in range(min(ng, 20000)):
                        o2 = best + 16 + k * 12
                        s0, e0 = struct.unpack(">II", d[o2:o2 + 8])
                        if s0 <= cp <= e0:
                            return True
                    return False
            except (struct.error, IndexError):
                return False
            return False

        return all(has(c) for c in chars)
    except (OSError, struct.error):
        return False


def _wm_font():
    """水印用的中文字体 (libass 经 fontsdir 加载); 没有则返回空。
    先看 FONT_DIR, 再扫系统字体目录 —— 以前只认 FONT_DIR, 字体没装就等于静默不出水印。"""
    now = time.time()
    if _FONT_CACHE["path"] and now - _FONT_CACHE["at"] < 20:
        if os.path.isfile(_FONT_CACHE["path"]):
            return _FONT_CACHE["path"]
    fp = ""
    for cand in _font_cands(FONT_DIR, 1):
        if _font_has_cjk(cand):
            fp = cand
            break
    if not fp:
        for d in FONT_ALTS:
            for cand in _font_cands(d, 3):
                if _font_has_cjk(cand):
                    fp = cand
                    break
            if fp:
                break
    _FONT_CACHE.update({"at": now, "path": fp})
    return fp


def _font_dir():
    """实际字体所在目录 (fontsdir 必须指向这里, 否则 libass 找不到)"""
    fp = _wm_font()
    return os.path.dirname(fp) if fp else FONT_DIR


def _font_reset():
    _FONT_CACHE.update({"at": 0.0, "path": ""})


def _wm_fontconf():
    """给 ffmpeg 自带的 fontconfig 一个最小配置 (精简系统上没有 /etc/fonts/fonts.conf,
    会导致 libass 的字体选择整个失效, 连矢量图形都不画)。返回配置文件路径。
    目录按实际字体位置写, FONT_DIR 不可写时退到 /tmp。"""
    d = _font_dir()
    for p in (os.path.join(FONT_DIR, "fonts.conf"), "/tmp/tsf-fonts.conf"):
        try:
            pd = os.path.dirname(p)
            if pd:
                os.makedirs(pd, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0"?>\n'
                        '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
                        '<fontconfig>\n  <dir>%s</dir>\n  <cachedir>/tmp/fccache</cachedir>\n'
                        '</fontconfig>\n' % d)
            return p
        except OSError:
            continue
    return ""


def _font_valid(fp, min_size=100 * 1024):
    """粗校验: TTF/OTF/TTC 的文件头 + 体积"""
    try:
        if os.path.getsize(fp) < min_size:
            return False
        with open(fp, "rb") as f:
            magic = f.read(4)
        return magic in (b"\x00\x01\x00\x00", b"true", b"ttcf", b"OTTO")
    except OSError:
        return False


def _font_download():
    """从官方 google/fonts 仓下载中文字体 (17MB) 到 FONT_DIR; 多镜像串行重试。
    返回 (ok, msg)。"""
    os.makedirs(FONT_DIR, exist_ok=True)
    dst = os.path.join(FONT_DIR, FONT_NAME)
    tmp = dst + ".part"
    errs = []
    for u in FONT_SRC:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "tsf-font/" + APP_VERSION})
            n = 0
            with urllib.request.urlopen(req, timeout=45) as r, open(tmp, "wb") as fo:
                while True:
                    b = r.read(262144)
                    if not b:
                        break
                    fo.write(b)
                    n += len(b)
                    if n > 40 * 1024 * 1024:
                        raise IOError("文件异常大")
            if not _font_valid(tmp, FONT_MIN) or not _font_has_cjk(tmp):
                raise IOError("下载内容不是有效的中文字体 (%d 字节)" % n)
            os.replace(tmp, dst)
            _font_reset()
            return True, "字体安装完成 (%.1fMB)" % (n / 1048576.0)
        except Exception as ex:
            errs.append("%s %s" % (u.split("/")[2], _err_kind(ex)))
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return False, "字体下载失败: " + "; ".join(errs[:3])


def _wm_tw(text, fs):
    """粗略估算文字宽度 (只用于胶囊宽度与槽位排布, 差几 px 不影响观感)"""
    w = 0.0
    for ch in str(text):
        if ord(ch) > 0x2E80:
            w += 1.0
        elif ch == " ":
            w += 0.28
        elif ch in "·:":
            w += 0.33
        elif ch == "%":
            w += 0.92
        elif ch.isdigit():
            w += 0.57
        elif ch.isupper():
            w += 0.68
        else:
            w += 0.52
    return w * fs


def _ass_pts(pts):
    def n(v):
        return ("%.1f" % v).rstrip("0").rstrip(".")
    return "m " + " l ".join("%s %s" % (n(x), n(y)) for x, y in pts)


def _ass_circle(cx, cy, r, steps=32):
    return _ass_pts([(cx + r * math.cos(2 * math.pi * i / steps),
                      cy + r * math.sin(2 * math.pi * i / steps)) for i in range(steps)])


def _ass_rrect(x, y, w, h, r, steps=6):
    """圆角矩形 (胶囊) 矢量路径"""
    r = min(r, w / 2.0, h / 2.0)
    pts = []
    for cx0, cy0, a0, a1 in ((x + w - r, y + r, -90, 0), (x + w - r, y + h - r, 0, 90),
                             (x + r, y + h - r, 90, 180), (x + r, y + r, 180, 270)):
        for i in range(steps + 1):
            a = math.radians(a0 + (a1 - a0) * float(i) / steps)
            pts.append((cx0 + r * math.cos(a), cy0 + r * math.sin(a)))
    return _ass_pts(pts)


def _ass_wheel(cx, cy, r, seg=16):
    """AP 方向盘徽标的两条矢量路径 (ASS p1 绘图): (圆形底, 方向盘图形)。
    圆环用多段四边形拼出, 不依赖 libass 的填充规则。"""
    badge = _ass_circle(cx, cy, r, 24)
    ir = r * 0.60
    lw = max(1.5, r * 0.17)
    parts = []
    for i in range(seg):
        a1, a2 = 2 * math.pi * i / seg, 2 * math.pi * (i + 1) / seg
        o1 = (cx + (ir + lw / 2) * math.cos(a1), cy + (ir + lw / 2) * math.sin(a1))
        o2 = (cx + (ir + lw / 2) * math.cos(a2), cy + (ir + lw / 2) * math.sin(a2))
        i1 = (cx + (ir - lw / 2) * math.cos(a1), cy + (ir - lw / 2) * math.sin(a1))
        i2 = (cx + (ir - lw / 2) * math.cos(a2), cy + (ir - lw / 2) * math.sin(a2))
        parts.append(_ass_pts([i1, o1, o2, i2]))
    b = lw / 2.0
    parts.append(_ass_pts([(cx - ir, cy - b), (cx + ir, cy - b), (cx + ir, cy + b), (cx - ir, cy + b)]))
    parts.append(_ass_pts([(cx - b, cy), (cx - b, cy + ir), (cx + b, cy + ir), (cx + b, cy)]))
    parts.append(_ass_circle(cx, cy, max(1.4, r * 0.14), 12))
    return badge, " ".join(parts)


def _wm_ass(fp, ss, dur, meta, size=(1280, 720)):
    """生成与网页播放器同款的行车信息水印 ASS 字幕 (导出视频用):
    顶部淡色窄条 + 左侧「日期时间 城市·街道」+ 右侧「AP 方向盘 / 车速 km/h / 转向灯 / 挡位 / 刹车 / 油门」。
    与前端 drawWm() 一一对应, 只是全部改成矢量色块 + 文字。
    片段没有行车遥测 (停车哨兵录的片段不写 SEI) 时退化成「时间 + 地点」,
    不再直接返回 None —— 否则用户勾了水印却拿到一段没有水印的视频。无字体时才返回 None。"""
    if not _wm_font():
        return None
    tel = telemetry_cached(fp) or {}
    frames = tel.get("frames") or []      # 空列表 = 该片段没有遥测, 只画时间地点
    has_tel = bool(frames)
    try:
        t0 = datetime.datetime.strptime(os.path.basename(fp)[:19], "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        t0 = None
    loc = " · ".join(x for x in (meta.get("city") or "", meta.get("street") or "") if x).strip()
    dur = int(dur)
    if dur < 1:
        return None
    W, H = size if size else (1280, 720)
    W, H = max(320, int(W)), max(240, int(H))
    # 水印大小跟画面高度走 (同样高度下观感一致, 4:3 的 960x720 也不会显得过小);
    # 极窄画面再用宽度兜底, 免得右侧元素挤出画外
    s = min(H / 720.0, W / 900.0)
    # 360p 这种超小画布: 字号给一个下限, 并去掉 km/h 与转向三角腾位置,
    # 否则 8px 的中文会被压成一团黑点; 480p 空间够, 仍保留完整元素
    narrow = W < 560
    if narrow:
        s = max(s, 0.72)

    pad = int(round(14 * s))
    bh = int(round(46 * s))                  # 顶部窄条高度
    yc = bh // 2
    f_date, f_loc = max(9, int(round(14 * s))), max(8, int(round(13 * s)))
    f_pill = max(9, int(round(12 * s)))      # 胶囊字号
    f_num = max(12, int(round(22 * s)))      # 车速
    f_unit = max(9, int(round(11 * s)))      # km/h
    f_gear = max(9, int(round(14 * s)))      # 挡位字母
    ph = int(round(24 * s))                  # 胶囊高
    ppad = int(round(18 * s))                # 胶囊左右内边距
    gap8, gap12 = int(round(8 * s)), int(round(12 * s))

    # ---- 右侧槽位从右往左一次算好, 每秒复用 (数字变宽只往左长, 不挤动别人) ----
    x = W - pad
    thr_w = max(ph * 2, int(round(_wm_tw("100%", f_pill) + ppad)))
    thr_x = x - thr_w
    x = thr_x - gap8
    brk_w = max(ph * 2, int(round(_wm_tw("刹车", f_pill) + ppad)))
    brk_x = x - brk_w
    x = brk_x - gap12
    gr = int(round(13 * s))                  # 挡位圆半径
    gear_cx = x - gr
    x = gear_cx - gr - int(round(10 * s))
    tri = int(round(9 * s))
    if not narrow:
        rtri_x = x - tri                     # 右转向灯 (尖朝右)
        x = rtri_x - int(round(7 * s))
        ltri_x = x - tri                     # 左转向灯 (尖朝左)
        x = ltri_x - gap12
    unit_w = int(round(_wm_tw("km/h", f_unit) * 1.06)) + 2   # 略放大: km/h 用左锚, 尾部留白更安全
    if not narrow:
        x -= unit_w + int(round(6 * s))
    num_right = x                            # 车速右对齐线 = km/h 左锚基准
    R = int(round(11 * s))                   # AP 方向盘半径
    wheel_gap = int(round(9 * s))            # 方向盘与车速之间的间距
    x -= int(round(_wm_tw("000", f_num))) + wheel_gap + R * 2

    C_WHITE, C_SOFT = "&H00FFFFFF&", "&H00F8F3EE&"
    C_THR, C_BRK, C_BRK_OFF = "&H00E07A1F&", "&H003A45FF&", "&H00322820&"
    C_GEAR, C_TRI_ON, C_TRI_OFF = "&H0059C734&", "&H000B9EF5&", "&H005F544A&"
    # AP 蓝 = 车机上自动驾驶图标的蓝 (#2f7cf6), ASS 用 BGR
    C_AP_ON, C_AP_OFF, C_AP_GLY = "&H00F67C2F&", "&H00382E26&", "&H00D6CCC3&"

    def esc(v):
        return str(v).replace("\\", "").replace("{", "").replace("}", "").replace("\n", " ")

    def ts(n):
        # 百分秒精度: 转向灯闪烁要切 0.4s 片段, 整秒精度会把整段闪成一片
        n = max(0.0, float(n))
        return "%d:%02d:%05.2f" % (int(n // 3600), int(n % 3600 // 60), n % 60)

    lines = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: %d" % W, "PlayResY: %d" % H,
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        # Wm: 带描边投影的文字; WmP: 胶囊/圆里的字 (无描边); WmV: 纯矢量色块
        "Style: Wm,Noto Sans SC,%d,&H00FFFFFF,&H00FFFFFF,&H78000000,&H60000000,1,0,0,0,100,100,0,0,1,1,1,7,0,0,0,1" % f_date,
        "Style: WmP,Noto Sans SC,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1" % f_pill,
        "Style: WmV,Noto Sans SC,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1" % f_pill,
        "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    def shape(a, b, color, path, alpha="&H00&", layer=1):
        lines.append("Dialogue: %d,%s,%s,WmV,,0,0,0,,{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\1c%s\\1a%s}%s{\\p0}"
                     % (layer, ts(a), ts(b), color, alpha, path))

    def txt(a, b, style, an, px, py, fs, color, s_text):
        lines.append("Dialogue: 2,%s,%s,%s,,0,0,0,,{\\an%d\\pos(%d,%d)\\fs%d\\1c%s}%s"
                     % (ts(a), ts(b), style, an, int(px), int(py), fs, color, esc(s_text)))

    def txt_raw(a, b, an, px, py, fs, body):
        """body 里允许内联标签 (一行里混字号/颜色), 交给 libass 自己排版"""
        lines.append("Dialogue: 2,%s,%s,Wm,,0,0,0,,{\\an%d\\pos(%d,%d)\\fs%d}%s"
                     % (ts(a), ts(b), an, int(px), int(py), fs, body))

    # 顶部窄条: 与原版一致的 rgba(13,18,26,.15)
    lines.append("Dialogue: 0,0:00:00.00,%s,,WmV,0,0,0,,{\\an7\\pos(0,0)\\bord0\\shad0"
                 "\\1c&H1A120D&\\alpha&HD9&\\p1}%s{\\p0}"
                 % (ts(dur), _ass_pts([(0, 0), (W, 0), (W, bh), (0, bh)])))

    def fr_at(ct):
        lo, hi, ans = 0, len(frames) - 1, frames[0]
        while lo <= hi:
            mid = (lo + hi) >> 1
            if frames[mid][0] <= ct:
                ans = frames[mid]
                lo = mid + 1
            else:
                hi = mid - 1
        return ans

    fr = [fr_at(ss + n) for n in range(dur)] if has_tel else []

    def spans(keyf):
        i = 0
        while i < dur:
            k = keyf(i)
            j = i
            while j + 1 < dur and keyf(j + 1) == k:
                j += 1
            yield i, j + 1, k
            i = j + 1

    def blink(a, b, period=0.4):
        """打灯时真正的闪烁: 按绝对时间的 0.4s 网格交替亮/灭, 只产出"亮"的时间片。
        相位按片段内秒数对齐, 和网页 HUD / canvas 水印用的是同一套节拍。"""
        k = int(math.floor(a / period))
        cur = float(a)
        while cur < b - 1e-6:
            nxt = min(float(b), (k + 1) * period)
            if nxt > cur and k % 2 == 0:
                yield cur, nxt
            cur = nxt
            k += 1

    # ---- 左: 日期时间 + 城市·街道 合成一行 (由 libass 顺序排版, 不依赖宽度估算) ----
    for n in range(dur):
        if t0 is not None:
            dt = t0 + datetime.timedelta(seconds=ss + n)
            date_s = dt.strftime("%m/%d %H:%M:%S" if narrow else "%Y/%m/%d %H:%M:%S")
        else:
            date_s = ""
        seg = []
        if date_s:
            seg.append("{\\1c%s}%s" % (C_WHITE, esc(date_s)))
        if loc:
            seg.append("{\\fs%d\\1c%s}%s" % (f_loc, C_SOFT, esc(loc)))
        if seg:
            txt_raw(n, n + 1, 4, pad, yc, f_date, "  ".join(seg))

    # ---- 右: 油门 / 刹车 / 挡位 / 转向灯 (状态相同的连续秒合并, 减小字幕体积) ----
    for a, b, k in (spans(lambda n: (int(round(fr[n][3])), bool(fr[n][5]), fr[n][1], fr[n][6]))
                    if has_tel else ()):
        thr, brk, gear, turn = k
        shape(a, b, C_THR, _ass_rrect(thr_x, yc - ph / 2.0, thr_w, ph, ph / 2.0))
        txt(a, b, "WmP", 5, thr_x + thr_w / 2.0, yc, f_pill, C_WHITE, "%d%%" % thr)
        shape(a, b, C_BRK if brk else C_BRK_OFF, _ass_rrect(brk_x, yc - ph / 2.0, brk_w, ph, ph / 2.0),
              "&H00&" if brk else "&H70&")
        txt(a, b, "WmP", 5, brk_x + brk_w / 2.0, yc, f_pill, C_WHITE if brk else C_SOFT, "刹车")
        shape(a, b, C_GEAR, _ass_circle(gear_cx, yc, gr, 28))
        txt(a, b, "WmP", 5, gear_cx, yc, f_gear, C_WHITE, gear)
        if not narrow:
            rt_path = _ass_pts([(rtri_x, yc - tri * 0.62), (rtri_x, yc + tri * 0.62), (rtri_x + tri, yc)])
            lt_path = _ass_pts([(ltri_x + tri, yc - tri * 0.62), (ltri_x + tri, yc + tri * 0.62), (ltri_x, yc)])
            # 底色常亮 (不打灯就是这颗暗灰三角), 亮色再按闪烁相位叠上去
            shape(a, b, C_TRI_OFF, rt_path)
            shape(a, b, C_TRI_OFF, lt_path)
            if turn in (1, 2):
                pth = rt_path if turn == 2 else lt_path
                for ga, gb in blink(a, b):
                    shape(ga, gb, C_TRI_ON, pth, layer=2)

    # ---- 右: AP 方向盘 + 车速 (按"车速 + AP 状态"分组; 数字变宽时方向盘跟着左移, 与网页一致) ----
    for a, b, k in (spans(lambda n: (max(0, int(round(fr[n][2]))), int(fr[n][7] or 0) in (1, 2, 3)))
                    if has_tel else ()):
        sp, on = k
        nw = _wm_tw(str(sp), f_num) * 1.04 + 1          # 宁大勿小: 估大只会让方向盘偏左一点
        disc, glyph = _ass_wheel(num_right - nw - wheel_gap - R, yc, R)
        shape(a, b, C_AP_ON if on else C_AP_OFF, disc, "&H00&" if on else "&H61&")
        shape(a, b, C_WHITE if on else C_AP_GLY, glyph, layer=2)
        # 数字右锚(6) / km/h 左锚(4): 位数变化只往左长, 两个元素永远不会互相压叠
        txt(a, b, "Wm", 6, num_right, yc, f_num, C_WHITE, str(sp))
        if not narrow:
            txt(a, b, "Wm", 4, num_right + int(round(6 * s)), yc, f_unit, C_SOFT, "km/h")

    p = os.path.join(RES_DIR, "wm-%s.ass" % hashlib.md5(
        ("%s|%d|%d|%dx%d|ap10|t%d" % (fp, int(ss), dur, W, H, len(frames))).encode()).hexdigest()[:16])
    with open(p, "w", encoding="utf-8") as fo:
        fo.write("\n".join(lines) + "\n")
    return p


def _make_push_video(fp, off, quality="480p", dur=30):
    """把触发摄像头那一路片段, 从触发点前 5 秒起截 dur 秒, 转成体积可控的 mp4; 返回缓存路径。
    有行车遥测(SEI)且设备上有字体时, 烧录与网页同款的行车信息水印 (手动保存的行车片段即有遥测;
    停车哨兵片段没有, 不烧)。"""
    h, kbps = VID_Q.get(quality) or VID_Q["480p"]
    dur = max(10, min(60, int(dur or 30)))
    ss = max(0.0, float(off) - 5.0)       # 触发点前 5 秒, 能看到"人走过来"的过程
    # 手动保存的片段: 触发点常在片段末尾, "前5秒起截"会只剩几秒。
    # 按实际时长钳制: 起点往前挪, 保证凑满 dur 秒且不越过片段末尾。
    try:
        clip_dur = probe_duration(fp) or 0.0
        if clip_dur > 0:
            dur = max(5, min(dur, int(clip_dur)))
            ss = max(0.0, min(ss, clip_dur - dur))
    except Exception:
        pass
    ass = ""
    try:
        if dur >= 10:
            meta = {}
            try:
                with open(os.path.join(os.path.dirname(fp), "event.json"), encoding="utf-8", errors="ignore") as f:
                    meta = json.load(f) or {}
            except Exception:
                meta = {}
            # 单路是 scale=-2:h, 真实宽度由源宽高比决定 (特斯拉原片 4:3 → 720p 只有 960 宽)。
            # ASS 的 PlayRes 必须等于真实输出尺寸, 否则 x 坐标会被按比例压缩而字号不变。
            sw, sh = probe_size(fp) or (1280, 960)
            ow = max(2, int(round(sw * float(h) / max(1, sh) / 2.0)) * 2)
            ass = _wm_ass(fp, ss, dur, meta, size=(ow, h)) or ""
    except Exception:
        ass = ""
    key = hashlib.md5(("%s|%d|%.2f|%s|%d|%s" % (fp, int(off), ss, quality, dur, "wm3" if ass else "-")).encode()).hexdigest()[:16]
    out = os.path.join(RES_DIR, "push-%s.mp4" % key)
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        return out
    if not os.path.isfile(FFMPEG_BIN):
        raise RuntimeError("设备上没有 ffmpeg")
    tmp = out + ".%d.tmp" % os.getpid()
    vf = "scale=-2:%d" % h
    if ass:
        vf += ",subtitles='%s':fontsdir='%s'" % (ass.replace(":", "\\:").replace("'", ""),
                                                 _font_dir().replace("'", ""))
    cmd = ["sh", "-c", 'echo 300 > /proc/self/oom_score_adj 2>/dev/null; exec "$0" "$@"',
           FFMPEG_BIN, "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "4",
           "-ss", "%.2f" % ss, "-t", str(dur), "-i", fp,
           "-vf", vf,
           "-c:v", "libx264", "-preset", "superfast",
           "-b:v", "%dk" % kbps, "-maxrate", "%dk" % (kbps * 3 // 2), "-bufsize", "%dk" % (kbps * 3),
           "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", "-f", "mp4", "-y", tmp]
    try:
        env = dict(os.environ)
        if ass:
            fc = _wm_fontconf()
            if fc:
                env["FONTCONFIG_FILE"] = fc
        with Q_SEM:        # 与点播转码共用并发闸门: 设备上 ffmpeg 总数恒定, 叠加会触发内核 lockup 重启
            r = subprocess.run(cmd, capture_output=True, timeout=300, env=env)
    except subprocess.TimeoutExpired:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise RuntimeError("转码超时 (>5 分钟)")
    if r.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise RuntimeError("转码失败: %s" % (r.stderr or b"")[:100].decode("utf-8", "ignore"))
    os.replace(tmp, out)
    try:
        res_cleanup()          # 推送视频也走同一个缓存目录, 超 2GB 从最旧删
    except Exception:
        pass
    return out


def _transcode_push_upload(src, quality="480p"):
    """把浏览器本机合成上传来的片段 (webm/mp4) 整段转成体积可控的 mp4, 供推飞书;
    返回 (mp4路径, 时长秒)。单路输入, 负载与推送转码同级, 设备可承受。"""
    h, kbps = VID_Q.get(quality) or VID_Q["480p"]
    try:
        st = os.stat(src)
    except OSError:
        raise RuntimeError("上传的片段不存在")
    key = hashlib.md5(("%d|%d|%s" % (st.st_size, int(st.st_mtime), quality)).encode()).hexdigest()[:16]
    out = os.path.join(RES_DIR, "push-manual-%s.mp4" % key)
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        return out, probe_duration(out) or 0.0
    if not os.path.isfile(FFMPEG_BIN):
        raise RuntimeError("设备上没有 ffmpeg")
    tmp = out + ".%d.tmp" % os.getpid()
    cmd = ["sh", "-c", 'echo 300 > /proc/self/oom_score_adj 2>/dev/null; exec "$0" "$@"',
           FFMPEG_BIN, "-nostdin", "-hide_banner", "-loglevel", "error",
           "-i", src, "-vf", "scale=-2:%d" % h,
           "-c:v", "libx264", "-preset", "superfast",
           "-b:v", "%dk" % kbps, "-maxrate", "%dk" % (kbps * 3 // 2), "-bufsize", "%dk" % (kbps * 3),
           "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", "-f", "mp4", "-y", tmp]
    try:
        with Q_SEM:        # 与点播转码共用并发闸门, 防止多路 ffmpeg 叠加触发内核 lockup 重启
            r = subprocess.run(cmd, capture_output=True, timeout=900)
    except subprocess.TimeoutExpired:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise RuntimeError("转码超时 (>15 分钟)")
    if r.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise RuntimeError("转码失败: %s" % (r.stderr or b"")[:120].decode("utf-8", "ignore"))
    os.replace(tmp, out)
    try:
        res_cleanup()
    except Exception:
        pass
    return out, probe_duration(out) or 0.0


def manual_push(conf, src, cat, name, quality="480p"):
    """把一个现成的视频文件 (浏览器合成的多路画面) 推到飞书私聊; 返回 (成功?, 提示)。
    src 会被整段转码后上传, 推完发送事件卡片 (带查看按钮)。"""
    if not _dm_ready(conf):
        return False, "飞书私聊未就绪: 需要在「推送」里配好 App ID/Secret + 接收人 (群机器人 webhook 发不了视频)"
    vid, dur = _transcode_push_upload(src, quality)
    mb = os.path.getsize(vid) / 1048576.0
    if mb > 28:
        return False, "转码后仍有 %.0fMB, 超过飞书 30MB 上限; 请选更短片段或更低清晰度" % mb
    fk = _feishu_upload_file(conf, vid, dur)
    _feishu_send_media(conf, fk)
    try:
        _feishu_send_dm(conf, _feishu_card(conf, cat, name, img_key=None))
    except Exception:
        pass
    return True, "已推送 %.0f 秒视频 (%.1fMB) 到飞书私聊" % (dur, mb)


def _feishu_upload_file(conf, path, dur=30):
    """上传视频文件到飞书, 返回 file_key"""
    with open(path, "rb") as f:
        data = f.read()
    bd = "----tsf%s" % hashlib.md5(("%s%.6f" % (path, time.time())).encode()).hexdigest()

    def fld(k, v):
        return ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (bd, k, v)).encode()

    body = (fld("file_type", "mp4") + fld("file_name", os.path.basename(path))
            + fld("duration", str(int(max(1, dur) * 1000)))
            + ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"clip.mp4\"\r\n"
               "Content-Type: video/mp4\r\n\r\n" % bd).encode()
            + data + ("\r\n--%s--\r\n" % bd).encode())
    raw = _http_post(FEISHU_API + "/im/v1/files", body, {
        "Authorization": "Bearer " + _feishu_token(conf),
        "Content-Type": "multipart/form-data; boundary=" + bd,
    }, timeout=180)
    j = json.loads(raw.decode("utf-8", "replace"))
    key = ((j or {}).get("data") or {}).get("file_key")
    if j.get("code") != 0 or not key:
        raise RuntimeError("上传视频失败: %s" % (j.get("msg") or j))
    return key


def _feishu_send_media(conf, file_key, image_key=""):
    """给本人发一条视频消息 (media)"""
    rid, rtype = _dm_target(conf)
    content = {"file_key": file_key}
    if image_key:
        content["image_key"] = image_key
    j = _post_json(FEISHU_API + "/im/v1/messages?receive_id_type=" + urllib.parse.quote(rtype),
                   {"receive_id": rid, "msg_type": "media", "content": json.dumps(content)},
                   timeout=60, headers={"Authorization": "Bearer " + _feishu_token(conf)})
    if j.get("code") != 0:
        raise RuntimeError("%s (code=%s)" % (j.get("msg") or "发视频失败", j.get("code")))
    return True


def _feishu_card(conf, cat, name, img_key=None, test=False):
    """拼一张飞书卡片 (标题/时间/位置/原因/镜头/封面/查看按钮)"""
    d = os.path.join(ARCHIVE, cat, name)
    meta = {}
    try:
        with open(os.path.join(d, "event.json"), encoding="utf-8", errors="ignore") as f:
            meta = json.load(f) or {}
    except Exception:
        pass
    cat_name, color, detail = _reason_info(meta.get("reason"))
    if cat == "SavedClips" and not str(meta.get("reason", "")).startswith("sentry_"):
        cat_name, color = "手动保存", "grey"
    cam = CAM_NUM.get(int(meta["camera"])) if str(meta.get("camera", "")).strip().isdigit() else None
    when = str(meta.get("timestamp") or name)[:19].replace("T", " ").replace("_", " ")
    try:
        dt = datetime.datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
        when = "%d月%d日 %02d:%02d:%02d" % (dt.month, dt.day, dt.hour, dt.minute, dt.second)
    except Exception:
        pass
    loc = " ".join(x for x in (meta.get("city") or "", meta.get("street") or "") if x).strip() or "位置未知"
    nclip = len(_ev_files(d))
    title = ("🧪 [测试] " if test else "🚨 ") + cat_name + (" · " + cam if cam else "")
    fields = [("时间", when), ("位置", loc), ("触发原因", detail)]
    if cam:
        fields.append(("触发镜头", "%s (#%s)" % (cam, meta.get("camera"))))
    fields.append(("片段", "%d 路画面" % nclip))
    els = []
    if img_key:
        els.append({"tag": "img", "img_key": img_key, "alt": {"tag": "plain_text", "content": "触发画面"}})
    for i in range(0, len(fields), 2):
        els.append({"tag": "div", "fields": [
            {"is_short": True, "text": {"tag": "lark_md", "content": "**%s**\n%s" % (k, v)}}
            for k, v in fields[i:i + 2]]})
    link = (conf.get("public_url") or "").rstrip("/")
    acts = []
    if link:
        acts.append({"tag": "button", "text": {"tag": "plain_text", "content": "查看录像"},
                     "url": "%s/?ev=%s/%s" % (link, urllib.parse.quote(cat), urllib.parse.quote(name)),
                     "type": "primary"})
    if acts:
        els.append({"tag": "action", "actions": acts})
    if test:
        els.append({"tag": "note", "elements": [{"tag": "plain_text", "content": "这是一条测试推送"}]})
    return {
        "config": {"wide_screen": True},
        "header": {"template": color, "title": {"tag": "plain_text", "content": title}},
        "elements": els,
    }


def _dm_target(conf):
    """返回 (receive_id, receive_id_type); 没配返回 (None, None)。
    自动识别: ou_/on_ → open_id, oc_ → chat_id, 含 @ → email"""
    rid = str(conf.get("receive_id") or "").strip()
    if not rid:
        return None, None
    t = str(conf.get("receive_id_type") or "").strip()
    if not t:
        if rid.startswith("oc_"):
            t = "chat_id"
        elif "@" in rid:
            t = "email"
        else:
            t = "open_id"
    return rid, t


def _dm_ready(conf):
    rid, _t = _dm_target(conf)
    return bool(rid and conf.get("app_id") and conf.get("app_secret"))


def _feishu_send_dm(conf, card):
    """用自建应用机器人给指定用户发卡片 — 只进你和机器人的单聊, 别人看不到"""
    rid, rtype = _dm_target(conf)
    url = FEISHU_API + "/im/v1/messages?receive_id_type=" + urllib.parse.quote(rtype)
    payload = {"receive_id": rid, "msg_type": "interactive",
               "content": json.dumps(card, ensure_ascii=False)}
    j = _post_json(url, payload, timeout=20,
                   headers={"Authorization": "Bearer " + _feishu_token(conf)})
    if j.get("code") != 0:
        raise RuntimeError("%s (code=%s)" % (j.get("msg") or "发送失败", j.get("code")))
    return True


def notify_push(cat, name, test=False):
    """推一条到飞书; 返回 (成功?, 提示)"""
    conf = notify_conf()
    dm = _dm_ready(conf)
    hook = str(conf.get("webhook") or "").strip()
    use_dm = dm and (conf.get("mode") != "group" or not hook)
    if not use_dm and not hook:
        return False, "未配置: 需要 App ID/Secret + 接收人 (私聊), 或群机器人 webhook"
    img_key = None
    warn = ""
    if conf.get("app_id") and conf.get("app_secret"):
        try:
            jpg, _m = _trigger_frame(cat, name)
            if jpg:
                img_key = _feishu_upload(conf, jpg)
            else:
                warn = " (没抽到封面帧)"
        except Exception as ex:
            warn = " (封面未附上: %s)" % str(ex)[:80]
    else:
        warn = " (未配 app_id/app_secret, 只发文字卡片)"
    # 视频模式: 先把触发摄像头那一路上传成视频消息, 再补一条精简卡片(带查看按钮)
    if use_dm and (conf.get("media") or "thumb") == "video":
        try:
            fp, off, _meta = _pick_clip(cat, name)
            if not fp:
                raise RuntimeError("归档里没有可用的片段")
            dur = int(conf.get("vdur") or 30)
            vid = _make_push_video(fp, off, conf.get("quality") or "480p", dur)
            fk = _feishu_upload_file(conf, vid, dur)
            _feishu_send_media(conf, fk, img_key or "")
            try:
                _feishu_send_dm(conf, _feishu_card(conf, cat, name, img_key=None, test=test))
            except Exception:
                pass
            mb = os.path.getsize(vid) / 1048576.0
            return True, "已推送 %d 秒视频 (%.1fMB) 到飞书私聊" % (dur, mb) + warn
        except Exception as ex:
            warn = " (视频没发成, 已回落封面卡片: %s)" % str(ex)[:90]
    card = _feishu_card(conf, cat, name, img_key=img_key, test=test)
    try:
        if use_dm:
            _feishu_send_dm(conf, card)
            return True, "已推送到你的飞书私聊" + warn
        j = _post_json(hook, {"msg_type": "interactive", "card": card})
        code = j.get("code", j.get("StatusCode", -1))
        if code not in (0, None):
            raise RuntimeError("%s (code=%s)" % (j.get("msg") or j.get("StatusMessage") or "发送失败", code))
    except Exception as ex:
        return False, "推送失败: %s" % str(ex)[:140]
    return True, "已推送到飞书群" + warn


def _ev_ts(name):
    """从事件目录名 YYYY-MM-DD_HH-MM-SS 解析事件真实发生时间; 失败返回 0"""
    try:
        return time.mktime(time.strptime(name, "%Y-%m-%d_%H-%M-%S"))
    except Exception:
        return 0


def notify_scan():
    """扫一遍归档, 把新出现的哨兵事件推给飞书; 返回本轮推送条数"""
    conf = notify_conf()
    if not conf.get("enabled") or not (_dm_ready(conf) or str(conf.get("webhook") or "").strip()):
        return 0
    st = _nstate_load()
    seen = st.setdefault("seen", {})
    tries = st.setdefault("try", {})
    first = not st.get("init")
    delay = max(5, int(conf.get("delay") or 20))
    cats = ["SentryClips"] + (["SavedClips"] if conf.get("saved") else [])
    sent = 0
    for cat in cats:
        if sent >= 3:
            break
        base = os.path.join(ARCHIVE, cat)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if not re.match(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$", name):
                continue
            key = cat + "/" + name
            if key in seen:
                continue
            d = os.path.join(base, name)
            newest = 0.0
            try:
                for f in os.listdir(d):
                    newest = max(newest, os.path.getmtime(os.path.join(d, f)))
            except OSError:
                continue
            now = time.time()
            if now - newest < delay:
                continue                     # 还在同步写入, 下一轮再看
            # 两道判定:
            # (1) 目录名里的日期 = 事件真实发生时间(车机时钟)。车机U盘循环覆盖后
            #     tesla-sync 会把旧片段重新归档, 复制出来的文件 mtime 是"复制时刻",
            #     只看 mtime 会把几天前的事件当新事件推出去。所以超过 24h 的直接记账不推
            #     (留 24h 余量足以吸收车机与盒子的时区偏差)。
            # (2) 新鲜度仍按 mtime: 保留"还在写入就不推""超过 6h 不补"的原语义。
            ev_ts = _ev_ts(name)
            if ev_ts and now - ev_ts > 24 * 3600:
                seen[key] = int(now)         # 历史回灌(一天以前的片段), 不推
                continue
            if first or now - newest > 6 * 3600:
                seen[key] = int(now)         # 首次启用不补历史; 太旧的(>6h)也不补
                continue
            ok, msg = notify_push(cat, name)
            st["last"] = {"at": int(time.time()), "ok": ok, "msg": msg, "ev": key}
            if ok:
                sent += 1
                seen[key] = int(now)
                tries.pop(key, None)
            else:
                tries[key] = tries.get(key, 0) + 1
                if tries[key] >= 3:
                    seen[key] = int(now)      # 连推 3 次都失败就放弃, 防止卡住队列
                    tries.pop(key, None)
            if sent >= 3:
                break
    if first:
        st["init"] = 1
    if len(seen) > 3000:                       # 防止状态文件无限膨胀
        for k in sorted(seen, key=lambda x: seen.get(x) or 0)[:len(seen) - 2000]:
            seen.pop(k, None)
    _nstate_save(st)
    return sent


def notify_loop():
    time.sleep(25)
    while True:
        if not storage_ready():
            time.sleep(30)
            continue
        try:
            notify_scan()
        except Exception:
            pass
        time.sleep(30)


def notify_status():
    conf = notify_conf()
    st = _nstate_load()
    rid, rtype = _dm_target(conf)
    return {
        "enabled": bool(conf.get("enabled")),
        "mode": conf.get("mode") or "dm",
        "webhook": conf.get("webhook") or "",
        "app_id": conf.get("app_id") or "",
        "has_secret": bool(conf.get("app_secret")),
        "receive_id": rid or "",
        "receive_id_type": rtype or "",
        "dm_ready": _dm_ready(conf),
        "public_url": conf.get("public_url") or "",
        "saved": bool(conf.get("saved")),
        "delay": int(conf.get("delay") or 20),
        "media": conf.get("media") or "thumb",
        "quality": conf.get("quality") or "480p",
        "vdur": int(conf.get("vdur") or 30),
        "last": st.get("last") or {},
        "sent_total": len(st.get("seen") or {}),
    }


def _variant_path(fp, qv, seconds=0):
    """清晰度缓存文件路径; 源文件一变 (size/mtime) 自然换 key, 不会拿旧缓存糊弄。
    seconds>0 表示只缓存前 N 秒的预缓冲, 与完整缓存分开 key。"""
    try:
        st = os.stat(fp)
    except OSError:
        return ""
    tag = "%s|%s" % (qv, ("p%d" % seconds) if seconds else "full")
    key = hashlib.md5(("%s|%d|%d|%s|%s" % (fp, st.st_size, st.st_mtime, tag, RES_ENC_VER)).encode()).hexdigest()
    base = PREVIEW_DIR if seconds else RES_DIR
    return os.path.join(base, key + ".mp4")


def _variant_ready(fp, qv, seconds=0):
    p = _variant_path(fp, qv, seconds)
    try:
        return bool(p) and os.path.getsize(p) > 0
    except OSError:
        return False


def _kill_transcode(p):
    try:
        os.killpg(p.pid, signal.SIGTERM)
    except OSError:
        try:
            p.terminate()
        except OSError:
            pass
    try:
        p.wait(timeout=2)
    except Exception:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            try:
                p.kill()
            except OSError:
                pass
        try:
            p.wait(timeout=2)
        except Exception:
            pass


def _run_transcode_cmd(cmd, cancel=None, timeout=900, env=None):
    """运行转码子进程; cancel 置位或超时立即杀掉整个进程组, 不留后台 FFmpeg。"""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, env=env)
    except Exception:
        return None
    deadline = time.time() + timeout
    while p.poll() is None:
        if cancel is not None and cancel.is_set():
            _kill_transcode(p)
            return None
        if time.time() > deadline:
            _kill_transcode(p)
            return None
        time.sleep(0.2)
    return p.returncode


def get_variant(fp, qv, slot=True, cancel=None, seconds=0):
    """返回 qv 清晰度的缓存文件路径; 没有就排队转码一份, 失败/取消回退原文件。
    slot=False 表示调用方已持有 Q_SEM; seconds>0 只生成前 N 秒预缓冲。"""
    out = _variant_path(fp, qv, seconds)
    if not out:
        return fp
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        return out
    if not os.path.isfile(FFMPEG_BIN):
        return fp
    if cancel is not None and cancel.is_set():
        return fp
    if slot:
        USER_TRANS[0] += 1
        try:
            got = Q_SEM.acquire(timeout=600)
        finally:
            USER_TRANS[0] = max(0, USER_TRANS[0] - 1)
        if not got:
            return fp
    try:
        if os.path.isfile(out) and os.path.getsize(out) > 0:
            return out
        if cancel is not None and cancel.is_set():
            return fp
        try:
            with open("/proc/meminfo") as mf:
                for line in mf:
                    if line.startswith("MemAvailable"):
                        if int(line.split()[1]) < 180000:
                            return fp
                        break
        except Exception:
            pass
        w, h, kbps = RES_SCALE[qv]
        tmp = out + ".%d_%d.tmp" % (os.getpid(), threading.get_ident())
        fps = 15 if qv == "360p" else 24
        preset = "ultrafast" if qv == "360p" else "superfast"
        enc_threads = "2" if seconds else "4"   # 预缓冲用更少线程, 降低空闲后台功耗峰值
        limit_args = ["-t", str(seconds)] if seconds else []
        soft_cmd = ["sh", "-c",
                    'echo 300 > /proc/self/oom_score_adj 2>/dev/null; exec "$0" "$@"',
                    FFMPEG_BIN, "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-threads", enc_threads, "-i", fp,
                    "-vf", "fps=%d,scale=%d:%d:force_original_aspect_ratio=decrease:flags=lanczos" % (fps, w, h),
                    "-c:v", "libx264", "-preset", preset,
                    "-b:v", "%dk" % kbps, "-maxrate", "%dk" % (kbps * 3 // 2),
                    "-bufsize", "%dk" % (kbps * 3),
                    "-c:a", "copy", "-movflags", "+faststart", "-f", "mp4"] + limit_args + ["-y", tmp]
        use_vpu = (qv == "360p" and os.access(VPU_TRANSCODE, os.X_OK)
                   and shutil.which("gst-launch-1.0") and shutil.which("media-ctl"))
        vpu_cmd = ["sh", "-c",
                   'echo 300 > /proc/self/oom_score_adj 2>/dev/null; exec "$0" "$@"',
                   VPU_TRANSCODE, fp, tmp, str(w), str(h), str(fps), str(kbps),
                   str(kbps * 3 // 2), str(kbps * 3), str(seconds or 0)]
        try:
            rc = None
            if use_vpu:
                rc = _run_transcode_cmd(vpu_cmd, cancel,
                                        env=dict(os.environ, FFMPEG=FFMPEG_BIN, FFPROBE=FFPROBE_BIN,
                                                 TSF_VPU_ENC_THREADS=enc_threads))
                if rc is None:
                    return fp
                if rc != 0:
                    print("[VPU] 360p 硬解转码失败, 回退软件", flush=True)
                    rc = _run_transcode_cmd(soft_cmd, cancel)
            else:
                rc = _run_transcode_cmd(soft_cmd, cancel)
            if rc is None:
                return fp
            if rc == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
                os.replace(tmp, out)
                if seconds:
                    try:
                        with open(out + ".src", "w", encoding="utf-8") as sf:
                            sf.write(fp)
                    except OSError:
                        pass
                    preview_cleanup()
                else:
                    res_cleanup()
                return out
        except Exception:
            pass
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return fp
    finally:
        if slot:
            Q_SEM.release()


# 后台转码作业: key=(源片, 画质, 秒数), 秒数0=完整, >0=预缓冲。
# 完整作业绑定播放器会话 owners; 会话退出/过期即取消。预缓冲 owner=None, 只由空闲循环调度。
_VARIANT_JOBS = {}
_VARIANT_JOBS_LOCK = threading.Lock()


def _drop_owner(key, sid):
    job = _VARIANT_JOBS.get(key)
    if not job:
        return
    job["owners"].discard(sid)
    if not job["owners"]:
        job["cancel"].set()


def playback_beat(sid, paths, q):
    if not sid:
        return
    now = time.time()
    with PLAYBACK_LOCK:
        PLAYBACK_SESSIONS[sid] = {"seen": now, "paths": set(paths or []), "q": q}
    # 切换清晰度后, 旧档位的完整转码不再需要, 立即停掉。
    with _VARIANT_JOBS_LOCK:
        for key in list(_VARIANT_JOBS):
            if key[2] == 0 and key[1] != q and sid in _VARIANT_JOBS[key]["owners"]:
                _drop_owner(key, sid)


def playback_leave(sid):
    if not sid:
        return
    with PLAYBACK_LOCK:
        PLAYBACK_SESSIONS.pop(sid, None)
    with _VARIANT_JOBS_LOCK:
        for key in list(_VARIANT_JOBS):
            if sid in _VARIANT_JOBS[key]["owners"]:
                _drop_owner(key, sid)


def playback_sweep_loop():
    while True:
        time.sleep(10)
        now = time.time()
        dead = []
        with PLAYBACK_LOCK:
            for sid, s in list(PLAYBACK_SESSIONS.items()):
                if now - s["seen"] > PLAYBACK_TTL:
                    dead.append(sid)
                    PLAYBACK_SESSIONS.pop(sid, None)
        for sid in dead:
            with _VARIANT_JOBS_LOCK:
                for key in list(_VARIANT_JOBS):
                    if sid in _VARIANT_JOBS[key]["owners"]:
                        _drop_owner(key, sid)


def spawn_variant(fp, qv, owner=None, seconds=0):
    """后台生成缓存; 同一 (文件,档位,秒数) 只起一个作业。owner 为播放器会话。"""
    if qv not in RES_SCALE or qv == "orig":
        return False
    if _variant_ready(fp, qv, seconds):
        return False
    key = (fp, qv, seconds)
    with _VARIANT_JOBS_LOCK:
        job = _VARIANT_JOBS.get(key)
        if job:
            if owner:
                job["owners"].add(owner)
            return False
        job = {"owners": {owner} if owner else set(), "cancel": threading.Event()}
        _VARIANT_JOBS[key] = job
    cancel = job["cancel"]

    def run():
        try:
            time.sleep(1.5)
            if cancel.is_set():
                return
            got = False
            deadline = time.time() + 600
            while time.time() < deadline:
                if cancel.is_set():
                    return
                if Q_SEM.acquire(timeout=1):
                    got = True
                    break
            if not got:
                return
            try:
                get_variant(fp, qv, slot=False, cancel=cancel, seconds=seconds)
            finally:
                Q_SEM.release()
        finally:
            with _VARIANT_JOBS_LOCK:
                _VARIANT_JOBS.pop(key, None)

    threading.Thread(target=run, daemon=True).start()
    return True

CAM_ORDER6 = ["left_pillar", "front", "right_pillar", "left_repeater", "back", "right_repeater"]
CAM_ORDER4 = ["front", "back", "left_repeater", "right_repeater"]


def cam_of(f):
    return f.rsplit("-", 1)[-1][:-4] if "-" in f else f


def clip_key(f):
    """文件名里的片段组标识: '2026-11-01_12-41-49-front.mp4' -> '2026-11-01_12-41-49'
    一个事件目录里常有 10 分钟的多组片段 (每组 4-6 路), 需要按组区分"""
    base = f[:-4] if f.lower().endswith(".mp4") else f
    return base.rsplit("-", 1)[0] if "-" in base else base


def latest_group(names):
    """取时间戳最新的一组片段 (与事件时间最接近的一组)"""
    if not names:
        return []
    groups = {}
    for f in names:
        groups.setdefault(clip_key(f), []).append(f)
    return groups[max(groups)]


def order_files(names):
    """按方位顺序排列 mp4: 6 路左右分列/前后居中, 4 路前后一排、左右B柱一排 (与前端 camSort 一致)"""
    order = CAM_ORDER6 if len(names) >= 6 else CAM_ORDER4
    return sorted(names, key=lambda f: (order.index(cam_of(f)) if cam_of(f) in order else 99, f))


# ---------- 归档视频 10 秒预缓冲 (系统盘, 空闲才跑) ----------
# 不再在列表页/后台预转完整视频。只为每个归档摄像头生成前 10 秒 360P 小缓存,
# 远程点开可先起播; 有人播放、有完整转码、有用户等待时立即让位。
PREWARM = {"on": os.environ.get("TSF_PREWARM", "1") != "0", "done": 0, "last": "", "skip": {}}
PREWARM_Q = "360p"
PREVIEW_SECONDS = 10


def _preview_pick():
    """挑一个还没有 10 秒预缓冲的归档视频, 新文件优先。"""
    best = None
    for cat in CATS:
        base = os.path.join(ARCHIVE, cat)
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for name in names:
            d = os.path.join(base, name)
            if not os.path.isdir(d):
                continue
            try:
                fs = os.listdir(d)
            except OSError:
                continue
            for f in fs:
                if not f.lower().endswith(".mp4"):
                    continue
                fp = os.path.join(d, f)
                if PREWARM["skip"].get(fp, 0) >= 2:
                    continue
                try:
                    mt = os.path.getmtime(fp)
                except OSError:
                    continue
                if time.time() - mt < 120:
                    continue
                if _variant_ready(fp, PREWARM_Q, PREVIEW_SECONDS):
                    continue
                if best is None or mt > best[0]:
                    best = (mt, fp, cat, name)
    return best


def prewarm_loop():
    """空闲时逐个生成 10 秒预缓冲; 播放/完整转码期间暂停。"""
    time.sleep(45)
    while True:
        try:
            if not storage_ready():
                time.sleep(30)
                continue
            if not PREWARM["on"]:
                time.sleep(600)
                continue
            preview_cleanup()
            with PLAYBACK_LOCK:
                playing = bool(PLAYBACK_SESSIONS)
            with _VARIANT_JOBS_LOCK:
                full_busy = any(k[2] == 0 for k in _VARIANT_JOBS)
            if playing or MEDIA_ACTIVE[0] > 0 or USER_TRANS[0] > 0 or full_busy:
                time.sleep(15)
                continue
            job = _preview_pick()
            if not job:
                time.sleep(60)
                continue
            _mt, fp, cat, name = job
            if not Q_SEM.acquire(blocking=False):
                time.sleep(15)
                continue
            try:
                get_variant(fp, PREWARM_Q, slot=False, seconds=PREVIEW_SECONDS)
                if _variant_ready(fp, PREWARM_Q, PREVIEW_SECONDS):
                    PREWARM["done"] += 1
                    PREWARM["last"] = "%s/%s · 10s" % (cat, name)
                    PREWARM["skip"].pop(fp, None)
                else:
                    PREWARM["skip"][fp] = PREWARM["skip"].get(fp, 0) + 1
                    time.sleep(30)
            finally:
                Q_SEM.release()
            time.sleep(2)
        except Exception:
            time.sleep(60)


def probe_duration(path):
    try:
        out = subprocess.run([FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", path],
                             capture_output=True, timeout=20).stdout.decode().strip()
        return float(out)
    except Exception:
        return 0.0


def probe_size(path):
    """返回视频 (宽, 高); 失败返回 None。水印 ASS 的 PlayResX/PlayResY 必须等于输出尺寸,
    否则 libass 会按 帧宽/PlayResX 压缩 x 坐标而字号不变, 元素之间会互相压叠。"""
    try:
        out = subprocess.run([FFPROBE_BIN, "-v", "error", "-select_streams", "v:0",
                              "-show_entries", "stream=width,height",
                              "-of", "csv=s=x:p=0", path],
                             capture_output=True, timeout=20).stdout.decode().strip()
        w, h = out.replace("\r", "").splitlines()[0].split("x")[:2]
        return int(w), int(h)
    except Exception:
        return None


def probe_fps(path):
    """返回视频帧率 (float); 失败返回 0。原画导出时用来保留源帧率。"""
    try:
        out = subprocess.run([FFPROBE_BIN, "-v", "error", "-select_streams", "v:0",
                              "-show_entries", "stream=r_frame_rate",
                              "-of", "default=nw=1:nk=1", path],
                             capture_output=True, timeout=20).stdout.decode().strip()
        num, _, den = out.partition("/")
        v = float(num) / (float(den) if den else 1.0)
        return v if 0 < v < 240 else 0.0
    except Exception:
        return 0.0


def mem_available_mb():
    """读取 MemAvailable, 用于合成前的内存兜底检查"""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return -1


def _stitch_worker(job_id, paths, out_path, total):
    n = len(paths)
    cols = 1 if n == 1 else (2 if n <= 4 else 3)
    # 每格分辨率: 默认 640x360 (4 路整幅 1280x720)。设备只有 1.4G 内存,
    # 输出 1080p 时 4 路 1080p 解码 + x264 帧缓存会把内存吃光导致整机失联。
    # 需要更高画质时用环境变量 TSF_CELL=800x450 之类覆盖。
    cell = os.environ.get("TSF_CELL", "").lower()
    if "x" in cell:
        try:
            W, H = [int(x) for x in cell.split("x", 1)]
        except ValueError:
            W, H = 640, 360
    elif n == 2:
        W, H = 960, 540      # 两路时整幅 1920x540, 负载可控
    else:
        W, H = 640, 360
    cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
           "-filter_threads", "1"]
    for f in paths:
        cmd += ["-i", f]
    fc = []
    for i in range(n):
        fc.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                  f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=15[v{i}]")
    layout = "|".join("%d_%d" % ((i % cols) * W, (i // cols) * H) for i in range(n))
    fc.append("".join(f"[v{i}]" for i in range(n)) + f"xstack=inputs={n}:layout={layout}:fill=black[vout]")
    cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
            "-threads", "2", "-x264-params", "ref=2:bframes=0",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats", out_path]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # 万一仍然吃爆内存, 让内核优先杀 ffmpeg, 保住 init/viewer 不被 OOM 带走
        try:
            with open("/proc/%d/oom_score_adj" % proc.pid, "w") as f:
                f.write("800")
        except OSError:
            pass
        deadline = time.time() + max(600, total * 30)  # 超时保护, 防止任务永久卡住
        timed_out = False
        for raw in proc.stdout:
            line = raw.decode("utf-8", "ignore").strip()
            if line.startswith("out_time_us=") and total > 0:
                try:
                    done = int(line.split("=", 1)[1]) / 1000000.0
                    pct = max(0, min(99, int(done / total * 100)))
                    with STITCH_LOCK:
                        if job_id in STITCH_JOBS:
                            STITCH_JOBS[job_id]["pct"] = pct
                except ValueError:
                    pass
            if time.time() > deadline:
                timed_out = True
                try:
                    proc.kill()
                except OSError:
                    pass
                break
        err = proc.stderr.read().decode("utf-8", "ignore")
        code = proc.wait()
        with STITCH_LOCK:
            job = STITCH_JOBS.get(job_id)
            if not job:
                return
            if timed_out:
                job["state"] = "error"
                job["err"] = "合成超时(超过 %d 分钟), 请少选几路再试" % int(max(600, total * 30) // 60)
                return
            if code == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                job["state"] = "done"
                job["pct"] = 100
                job["path"] = out_path
                job["size"] = os.path.getsize(out_path)
            else:
                job["state"] = "error"
                tail = [l for l in (err or "").strip().splitlines() if l.strip()]
                job["err"] = (tail[-1] if tail else "ffmpeg 退出码 %d" % code)[:300]
    except Exception as e:
        with STITCH_LOCK:
            job = STITCH_JOBS.get(job_id)
            if job:
                job["state"] = "error"
                job["err"] = str(e)[:300]


def start_stitch(cat, name, cams):
    """创建合成任务, 返回 (job_id, 错误信息)"""
    # 本机系统盘 IO 与内存有限, 实测 ffmpeg 多路 1080p 解码+编码会触发
    # 内核 soft/hard lockup -> panic=5 自动重启, 已用 2/4 路真实素材复现两次。
    # 前端默认走浏览器本机合成, 这里仅保留 TSF_STITCH=1 的实验开关。
    if os.environ.get("TSF_STITCH", "0") != "1":
        return None, "设备端合成已停用(该负载会触发设备内核重启), 请使用浏览器合成或打包下载"
    if not os.path.isfile(FFMPEG_BIN):
        return None, "设备上未安装 ffmpeg (预期 %s)" % FFMPEG_BIN
    evdir = safe_archive_dir(os.path.join(ARCHIVE, cat, name))
    if not evdir or not os.path.isdir(evdir):
        return None, "事件不存在"
    files = [f for f in os.listdir(evdir) if f.lower().endswith(".mp4")]
    files = latest_group(files)  # 只取最新一组片段, 24 个片段全拼会直接压垮设备
    if cams:
        files = [f for f in files if cam_of(f) in cams]
    files = order_files(files)
    if len(files) < 2:
        return None, "至少需要选择两路画面"
    paths = [os.path.join(evdir, f) for f in files]
    os.makedirs(STITCH_DIR, exist_ok=True)
    # 内存与并发保护: 设备只有 1.4G, 同时跑两个合成会直接 OOM 拖垮整机
    with STITCH_LOCK:
        running = [j for j in STITCH_JOBS.values() if j.get("state") == "running"]
    if running:
        return None, "已有合成任务在进行, 请等待完成后再试"
    avail = mem_available_mb()
    if 0 < avail < 300:
        return None, "设备可用内存不足(%dMB), 暂停合成以免影响录像同步" % avail
    now = time.time()
    for old_f in os.listdir(STITCH_DIR):
        fp_old = os.path.join(STITCH_DIR, old_f)
        try:
            if os.path.isfile(fp_old) and now - os.path.getmtime(fp_old) > 7200:
                os.unlink(fp_old)
        except OSError:
            pass
    job_id = "%s-%d" % (name.replace(":", "-"), int(time.time() * 1000) % 1000000)
    out_path = os.path.join(STITCH_DIR, job_id + ".mp4")
    total = probe_duration(paths[0])
    with STITCH_LOCK:
        STITCH_JOBS[job_id] = {"state": "running", "pct": 0, "path": None,
                               "name": "%s_%d路.mp4" % (name, len(files)), "total": total}
    threading.Thread(target=_stitch_worker, args=(job_id, paths, out_path, total), daemon=True).start()
    return job_id, None


# ---------- 服务端"带水印导出": 给 iOS / 微信 一份标准 H.264 mp4 ----------
# 为什么不用浏览器合成: iOS Safari 的 MediaRecorder 只认 video/webm (微信发不出去),
# iOS 26 起录 mp4 还会被截断(实测只留前几秒)。所以苹果设备改由设备端 ffmpeg 出片。
# 负载控制: 多路时先逐路单独降采样成小文件(同时只解 1 路 1080p), 再拼小文件,
# 避免 2~4 路 1080p 同时解码触发内核 lockup。
# 0 表示"原画": 按源分辨率出片 (单路 1280x960 就是 1280x960, 不再降到 720 行)
EXPORT_Q = {"720p": 720, "480p": 480, "360p": 360, "orig": 0}


def _ffrun(cmd, timeout=900):
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as ex:
        return -1, str(ex)
    try:
        with open("/proc/%d/oom_score_adj" % p.pid, "w") as f:
            f.write("800")            # 内存吃紧时先杀 ffmpeg, 保住主服务
    except OSError:
        pass
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            p.kill()
        except OSError:
            pass
        return -1, "转码超时"
    return p.returncode, (err or b"").decode("utf-8", "ignore")[-300:]


def _export_worker(job_id, paths, out_path, total, wm, q="720p"):
    n = len(paths)
    tmpdir = os.path.join(STITCH_DIR, "ex-" + job_id.replace("/", "_"))
    os.makedirs(tmpdir, exist_ok=True)

    def setpct(v):
        with STITCH_LOCK:
            job = STITCH_JOBS.get(job_id)
            if job:
                job["pct"] = max(0, min(99, int(v)))

    def fail(msg):
        with STITCH_LOCK:
            job = STITCH_JOBS.get(job_id)
            if job:
                job["state"] = "error"
                job["err"] = (msg or "ffmpeg 失败")[:300]

    try:
        # 画面尺寸: 单路保持源比例; 多路也按源画面比例取格子, 不留黑边
        # (以前多路固定 1280x720 再把 4:3 的源 pad 进 16:9 格子, 每格左右各 12.5% 黑边)
        sw, sh = probe_size(paths[0]) or (1280, 960)
        sw, sh = max(2, int(sw)), max(2, int(sh))
        target = EXPORT_Q.get(q, 720)                 # 0 = 原画
        fps = 15
        if q == "orig":
            # 原画保留源帧率 (车机大多是 36fps, 封顶 30: 再高只会拖慢编码, 肉眼看不出)
            fps = max(15, min(30, int(round(probe_fps(paths[0])) or 15)))
        cell = []                                     # 每路的目标格子 (w, h)
        pos = []                                      # 每路在画布里的左上角
        if n == 1:
            OH = target or sh
            OH -= OH % 2
            OW = max(2, int(round(sw * float(OH) / sh / 2.0)) * 2)
        else:
            cols, rows = 2, (n + 1) // 2
            base = target or min(960, sh)             # 多路"原画"封顶 960: 4 路同时解 1080p 会吃满内存
            CH = max(2, (base // rows) - (base // rows) % 2)
            CW = max(2, int(round(sw * float(CH) / sh / 2.0)) * 2)
            # 画布像素兜底 (1.4MP): 2 路时 1920x720 已经够大, 再多只会拖慢编码
            px = CW * cols * CH * rows
            if px > 1400000:
                k = math.sqrt(1400000.0 / px)
                CH = max(2, int(round(CH * k / 2.0)) * 2)
                CW = max(2, int(round(sw * float(CH) / sh / 2.0)) * 2)
            OW, OH = CW * cols, CH * rows
            cell = [(CW, CH)] * n
            pos = [((i % 2) * CW, (i // 2) * CH) for i in range(n)]
            if n == 3:
                # 3 路: 第三路铺满下面一整行, 不留一块黑格子
                cell[2] = (CW * 2, CH)
                pos[2] = (0, CH)

        # 第一步: 逐路降采样 (顺序执行, 峰值只有 1 路 1080p 解码)
        small = []
        if n > 1:
            for i, fp in enumerate(paths):
                sp = os.path.join(tmpdir, "c%d.mp4" % i)
                cw, ch = cell[i] if i < len(cell) else (CW, CH)
                vf = ("scale=%d:%d:force_original_aspect_ratio=increase,"
                      "crop=%d:%d,setsar=1,fps=%d" % (cw, ch, cw, ch, fps))
                code, err = _ffrun([FFMPEG_BIN, "-nostdin", "-hide_banner", "-loglevel", "error",
                                    "-threads", "2", "-i", fp, "-vf", vf, "-an",
                                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                                    "-threads", "2", "-y", sp], timeout=600)
                if code != 0 or not os.path.isfile(sp):
                    fail(err or ("第 %d 路降采样失败" % (i + 1)))
                    return
                small.append(sp)
                setpct((i + 1) / float(n) * 70)
        else:
            small = paths

        ass = ""
        if wm:
            try:
                meta = {}
                try:
                    with open(os.path.join(os.path.dirname(paths[0]), "event.json"),
                              encoding="utf-8", errors="ignore") as f:
                        meta = json.load(f) or {}
                except Exception:
                    meta = {}
                ass = _wm_ass(paths[0], 0, probe_duration(paths[0]) or 0, meta,
                              size=(OW, OH)) or ""
            except Exception:
                ass = ""
        if wm and not ass:
            # 勾了水印却没生成字幕: 宁可报错, 也不要给用户一段没有水印的视频
            fail("水印生成失败 (设备缺少中文字体?) — 请点「安装字体」后重试")
            return

        cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-filter_threads", "1"]
        for f in small:
            cmd += ["-i", f]
        fc = []
        if n == 1:
            fc.append("[0:v]scale=%d:%d,setsar=1,fps=%d[v0]" % (OW, OH, fps))
            last = "[v0]"
        else:
            for i in range(n):
                fc.append("[%d:v]setsar=1[v%d]" % (i, i))
            cells = "|".join("%d_%d" % (pos[i][0], pos[i][1]) for i in range(n))
            fc.append("".join("[v%d]" % i for i in range(n)) +
                      "xstack=inputs=%d:layout=%s:fill=black[vg]" % (n, cells))
            last = "[vg]"
        if ass:
            sub = "subtitles='%s':fontsdir='%s'" % (ass.replace(":", "\\:").replace("'", ""),
                                                    _font_dir().replace("'", ""))
            fc.append("%s%s[vout]" % (last, sub))
            last = "[vout]"
        cmd += ["-filter_complex", ";".join(fc), "-map", last, "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "25", "-pix_fmt", "yuv420p",
                "-threads", "2", "-c:a", "aac", "-b:a", "96k",
                "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", out_path]
        env = dict(os.environ)
        if ass:
            fcnf = _wm_fontconf()
            if fcnf:
                env["FONTCONFIG_FILE"] = fcnf
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        try:
            with open("/proc/%d/oom_score_adj" % p.pid, "w") as f:
                f.write("800")
        except OSError:
            pass
        deadline = time.time() + max(600, (total or 60) * 40)
        for raw in p.stdout:
            line = raw.decode("utf-8", "ignore").strip()
            if line.startswith("out_time_us=") and total:
                try:
                    done = int(line.split("=", 1)[1]) / 1000000.0
                    setpct(70 + min(29, done / float(total) * 29))
                except ValueError:
                    pass
            if time.time() > deadline:
                try:
                    p.kill()
                except OSError:
                    pass
                break
        err = p.stderr.read().decode("utf-8", "ignore")
        code = p.wait()
        if code == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            with STITCH_LOCK:
                job = STITCH_JOBS.get(job_id)
                if job:
                    job["state"] = "done"
                    job["pct"] = 100
                    job["path"] = out_path
                    job["size"] = os.path.getsize(out_path)
        else:
            tail = [x for x in (err or "").strip().splitlines() if x.strip()]
            fail(tail[-1] if tail else ("ffmpeg 退出码 %d" % code))
    except Exception as ex:
        fail(str(ex))
    finally:
        try:
            for f in os.listdir(tmpdir):
                os.unlink(os.path.join(tmpdir, f))
            os.rmdir(tmpdir)
        except OSError:
            pass


def start_export(cat, name, cams, wm=True, q="720p", files=None):
    """创建"服务端带水印导出"任务, 返回 (job_id, 错误)
    files: 前端指定要导出的具体片段文件名 (用户正在看的那一分钟),
           不传则退回"最新一组"的行为。"""
    if not os.path.isfile(FFMPEG_BIN):
        return None, "设备上没有 ffmpeg, 无法生成 mp4"
    # 字体缺失时绝不静默出无水印视频 (2.8.18 之前就是这样: 用户勾了水印拿到一段干干净净的片子)
    if wm and not _wm_font():
        return None, ("设备缺少中文字体, 水印烧不进去: 请先点「安装字体」(约 17MB) 再导出, "
                      "或取消勾选水印直接导出视频")
    evdir = safe_archive_dir(os.path.join(ARCHIVE, cat, name))
    if not evdir or not os.path.isdir(evdir):
        return None, "事件不存在"
    if isinstance(files, list) and files:
        picked = []
        for f in files:
            b = safe_name(str(f))
            if not b or not b.lower().endswith(".mp4"):
                continue
            if not os.path.isfile(os.path.join(evdir, b)):
                continue
            if cams and cam_of(b) not in cams:
                continue
            if b not in picked:
                picked.append(b)
        files = order_files(picked) if picked else []
    else:
        files = [f for f in os.listdir(evdir) if f.lower().endswith(".mp4")]
        files = latest_group(files)
        if cams:
            files = [f for f in files if cam_of(f) in cams]
        files = order_files(files)
    if not files:
        return None, "没有可导出的片段"
    with STITCH_LOCK:
        if any(j.get("state") == "running" for j in STITCH_JOBS.values()):
            return None, "已有导出/合成任务在进行, 请等它完成"
    avail = mem_available_mb()
    if 0 < avail < 260:
        return None, "设备可用内存不足(%dMB), 稍后再试" % avail
    paths = [os.path.join(evdir, f) for f in files]
    os.makedirs(STITCH_DIR, exist_ok=True)
    now = time.time()
    for old in os.listdir(STITCH_DIR):
        p = os.path.join(STITCH_DIR, old)
        try:
            if os.path.isfile(p) and now - os.path.getmtime(p) > 3600:
                os.unlink(p)
        except OSError:
            pass
    job_id = "%s-ex%d" % (name.replace(":", "-"), int(now * 1000) % 1000000)
    out_path = os.path.join(STITCH_DIR, job_id + ".mp4")
    total = probe_duration(paths[0]) or 60
    with STITCH_LOCK:
        STITCH_JOBS[job_id] = {"state": "running", "pct": 0, "path": None, "size": 0,
                               "name": "%s_%d路.mp4" % (name, len(files))}
    threading.Thread(target=_export_worker,
                     args=(job_id, paths, out_path, total, bool(wm), q), daemon=True).start()
    return job_id, None


# ---------- 行车遥测: 解码视频 SEI 里的 SeiMetadata protobuf ----------
# Tesla 在车辆行驶中录制的片段里, 每帧塞一条 SEI(type 6) NAL,
# payload 以 magic 0x42 0x42 0x69 开头, 后跟 protobuf:
#   1 version, 2 gear(0P/1D/2R/3N), 3 frame_seq, 4 speed_mps, 5 油门%,
#   6 方向盘角度, 7/8 左右转向灯, 9 刹车, 10 AP状态, 11/12 经纬度,
#   13 航向, 14/15/16 三轴加速度
TEL_DIR = os.environ.get("TSF_CACHE", "/opt/tesla-sentry/cache") + "/tel-cache"
TEL_SEM = threading.BoundedSemaphore(int(os.environ.get("TSF_TEL_CONN", "1")))


def _pb_varint(b, i):
    r = 0
    s = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << s
        if not x & 0x80:
            return r, i
        s += 7


def _pb_decode(b):
    out = {}
    i = 0
    n = len(b)
    while i < n:
        try:
            key, i = _pb_varint(b, i)
        except (IndexError, ValueError):
            break
        fn, wt = key >> 3, key & 7
        try:
            if wt == 0:
                out[fn], i = _pb_varint(b, i)
            elif wt == 5:
                out[fn] = struct.unpack("<f", b[i:i + 4])[0]
                i += 4
            elif wt == 1:
                out[fn] = struct.unpack("<d", b[i:i + 8])[0]
                i += 8
            elif wt == 2:
                ln, j = _pb_varint(b, i)
                i = j + ln
            else:
                return None
        except (IndexError, struct.error, ValueError):
            return None
    return out if i == n else None


def _strip_emulation(b):
    out = bytearray()
    zeros = 0
    for x in b:
        if zeros >= 2 and x == 3:
            zeros = 0
            continue
        out.append(x)
        zeros = zeros + 1 if x == 0 else 0
    return bytes(out)


def _mp4_video_samples(fp, max_samples=4000):
    """解析 moov, 返回 [(offset, size), ...] 与 lenSize; 失败返回 None"""
    with open(fp, "rb") as f:
        d = f.read(4096)
        f.seek(0, 2)
        fsize = f.tell()

    def boxes(buf, start, end):
        out = []
        i = start
        while i + 8 <= end:
            if i + 8 > len(buf) and len(buf) < fsize:
                return None  # 需要 moov 全量, 由调用方重新读
            size = struct.unpack(">I", buf[i:i + 4])[0]
            typ = buf[i + 4:i + 8]
            hdr = 8
            if size == 1:
                size = struct.unpack(">Q", buf[i + 8:i + 16])[0]
                hdr = 16
            elif size == 0:
                size = end - i
            if size < hdr:
                break
            out.append((typ, i + hdr, i + size))
            i += size
        return out

    # moov 可能在文件尾, 先定位
    with open(fp, "rb") as f:
        pos = 0
        moov_rng = None
        while pos + 8 <= fsize:
            f.seek(pos)
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            size = struct.unpack(">I", hdr[:4])[0]
            typ = hdr[4:8]
            hsz = 8
            if size == 1:
                size = struct.unpack(">Q", f.read(8))[0]
                hsz = 16
            elif size == 0:
                size = fsize - pos
            if size < hsz:
                break
            if typ == b"moov":
                moov_rng = (pos + hsz, pos + size)
                break
            pos += size
    if not moov_rng:
        return None
    with open(fp, "rb") as f:
        f.seek(moov_rng[0])
        moov = f.read(moov_rng[1] - moov_rng[0])
    mv_s, mv_e = 0, len(moov)

    def find1(name, s, e):
        for typ, cs, ce in boxes(moov, s, e):
            if typ == name:
                return cs, ce
        return None

    stbl = None
    for typ, ts, te in boxes(moov, mv_s, mv_e):
        if typ != b"trak":
            continue
        r = find1(b"mdia", ts, te)
        if not r:
            continue
        r2 = find1(b"minf", r[0], r[1])
        if not r2:
            continue
        r3 = find1(b"stbl", r2[0], r2[1])
        if not r3:
            continue
        stsd = find1(b"stsd", r3[0], r3[1])
        if stsd and moov.find(b"avcC", stsd[0], stsd[1]) > 0:
            stbl = r3
            break
    if not stbl:
        return None
    s, e = stbl
    stsd = find1(b"stsd", s, e)
    avc = moov.find(b"avcC", stsd[0], stsd[1])
    len_size = (moov[avc + 8] & 3) + 1
    a = find1(b"stsz", s, e)[0]
    uniform = struct.unpack(">I", moov[a + 4:a + 8])[0]
    n = struct.unpack(">I", moov[a + 8:a + 12])[0]
    if uniform:
        sizes = [uniform] * n
        buf = b""
    else:
        take = min(n, max_samples * 2)
        sizes = list(struct.unpack(">%dI" % take, moov[a + 12:a + 12 + 4 * take]))
    ca = find1(b"stco", s, e)[0]
    nch = struct.unpack(">I", moov[ca + 4:ca + 8])[0]
    chunks = struct.unpack(">%dI" % nch, moov[ca + 8:ca + 8 + 4 * nch])
    sa = find1(b"stsc", s, e)[0]
    ns = struct.unpack(">I", moov[sa + 4:sa + 8])[0]
    stsc = struct.unpack(">%dIII" % ns, moov[sa + 8:sa + 8 + 12 * ns])
    offs = []
    si = 0
    for ci in range(nch):
        run = None
        for k in range(ns):
            if stsc[k * 3] - 1 <= ci:
                run = stsc[k * 3:k * 3 + 3]
        per = run[1] if run else 1
        o = chunks[ci]
        for _ in range(per):
            if si >= len(sizes) or len(offs) >= max_samples:
                break
            offs.append((o, sizes[si]))
            o += sizes[si]
            si += 1
    return offs, len_size


def parse_telemetry(fp, stride=3):
    """从 mp4 SEI 提取遥测, 返回 dict 或 None(无SEI)"""
    r = _mp4_video_samples(fp)
    if not r:
        return None
    offs, len_size = r
    dur = probe_duration(fp)
    if not dur or len(offs) < 2:
        return None
    fps = len(offs) / float(dur)
    fsize = os.path.getsize(fp)
    frames = []
    gear_map = {0: "P", 1: "D", 2: "R", 3: "N"}
    with open(fp, "rb") as f, TEL_SEM:
        for k in range(0, len(offs), stride):
            o, ln = offs[k]
            if o + ln > fsize:
                continue
            f.seek(o)
            data = f.read(ln)
            pos = 0
            while pos + len_size <= len(data):
                n2 = int.from_bytes(data[pos:pos + len_size], "big")
                if n2 <= 0 or pos + len_size + n2 > len(data):
                    break
                nal = data[pos + len_size:pos + len_size + n2]
                pos += len_size + n2
                if nal[0] & 0x1F != 6:
                    continue
                # 找 magic: 连续的 0x42 之后遇到 0x69
                pi = None
                for i in range(3, min(len(nal), 100)):
                    if nal[i] == 0x42:
                        continue
                    if nal[i] == 0x69:
                        pi = i + 1
                    break
                if pi is None:
                    continue
                payload = _strip_emulation(nal[pi:len(nal) - 1])
                msg = _pb_decode(payload)
                if not msg:
                    continue
                spd = msg.get(4, 0.0) * 3.6
                frames.append([
                    round(k / fps, 2),
                    gear_map.get(msg.get(2, 1), "D"),
                    round(spd, 1),
                    int(round(msg.get(5, 0.0))),
                    round(msg.get(6, 0.0), 1),
                    1 if msg.get(9) else 0,
                    1 if msg.get(7) else (2 if msg.get(8) else 0),
                    int(msg.get(10, 0)),
                    round(msg.get(11, 0.0), 6),
                    round(msg.get(12, 0.0), 6),
                    round(msg.get(13, 0.0), 1),
                    round(msg.get(14, 0.0), 2),
                    round(msg.get(15, 0.0), 2),
                    round(msg.get(16, 0.0), 2),
                ])
    if not frames:
        return None
    speeds = [f[2] for f in frames]
    brakes = sum(1 for f in frames if f[5])
    return {
        "fps": round(fps, 2),
        "count": len(offs),
        "duration": round(dur, 2),
        "max_speed": max(speeds),
        "avg_speed": round(sum(speeds) / len(speeds), 1),
        "brake_ratio": round(brakes * 100.0 / len(frames), 1),
        "frames": frames,
    }


def telemetry_cached(fp):
    os.makedirs(TEL_DIR, exist_ok=True)
    try:
        st = os.stat(fp)
    except OSError:
        return None
    key = hashlib.md5(("%s|%d|%d" % (fp, st.st_mtime_ns, st.st_size)).encode()).hexdigest()
    cache = os.path.join(TEL_DIR, key + ".json")
    if os.path.isfile(cache):
        try:
            with open(cache, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    try:
        result = parse_telemetry(fp)
    except Exception:
        result = None
    if result:
        try:
            tmp = cache + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(result, f, separators=(",", ":"))
            os.replace(tmp, cache)
        except OSError:
            pass
    return result


# ---------- 访问认证 ----------
# 默认关闭; 只要配了密码 (auth.conf 里的 pass= 或 sha256=) 就全站开启。
# 除登录页外, 页面/媒体流/下载/接口全部要过认证; 用 HMAC 签名 cookie (默认 30 天) 记住登录,
# 这样 <video>、缩略图、zip 下载这些子请求不会反复弹窗; 同时兼容 HTTP Basic 方便 curl。
# 配置文件: /opt/tesla-sentry/auth.conf  (user= / pass= / sha256= / secret= / ttl=)
AUTH_FILE = os.environ.get("TSF_AUTH_FILE", "/opt/tesla-sentry/auth.conf")


AUTH_CONF_ERR = None   # 非空 = auth.conf 异常, 启动时拒绝运行, 避免静默变成无认证


def _auth_conf():
    """读 auth.conf。文件不存在 = 用户主动关闭认证 (保留这个用法);
    文件存在却读不了 / 读不出凭据 = 配置损坏, 记下来由启动流程拒绝运行。"""
    global AUTH_CONF_ERR
    d = {}
    try:
        with open(AUTH_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                d[k.strip().lower()] = v.strip()
    except FileNotFoundError:
        pass
    except OSError as ex:
        AUTH_CONF_ERR = "auth.conf 读取失败: %s" % ex
    return d


_AC = _auth_conf()
AUTH_USER = os.environ.get("TSF_AUTH_USER") or _AC.get("user") or "admin"
AUTH_PASS = os.environ.get("TSF_AUTH_PASS") or _AC.get("pass") or ""
AUTH_SHA = (os.environ.get("TSF_AUTH_SHA256") or _AC.get("sha256") or "").strip().lower()
AUTH_SECRET = (os.environ.get("TSF_AUTH_SECRET") or _AC.get("secret") or "") or ("tsf-v1|" + (AUTH_SHA or AUTH_PASS))
AUTH_TTL = int(os.environ.get("TSF_AUTH_TTL") or _AC.get("ttl") or 30 * 86400)
AUTH_ON = bool(AUTH_SHA or AUTH_PASS)
if (AUTH_CONF_ERR is None and os.path.exists(AUTH_FILE) and not AUTH_ON
        and not (os.environ.get("TSF_AUTH_PASS") or os.environ.get("TSF_AUTH_SHA256"))):
    AUTH_CONF_ERR = "auth.conf 存在但没有 pass= / sha256=, 内容可能已损坏"
FAILS = {}                       # ip -> [失败次数, 首次失败时间]
FAIL_LOCK = threading.Lock()


def pw_ok(pw):
    if AUTH_SHA:
        return hmac.compare_digest(hashlib.sha256(pw.encode()).hexdigest(), AUTH_SHA)
    return hmac.compare_digest((pw or "").encode(), AUTH_PASS.encode())


def auth_set_pass(old, new):
    """改网页登录密码; 返回 (成功?, 提示)。成功后重写 auth.conf 与内存凭据,
    并换一个随机 secret → 其它设备上的旧 cookie 立刻失效, 只有本机(前端会用新密码重新登录)继续。"""
    global AUTH_PASS, AUTH_SHA, AUTH_SECRET, AUTH_ON
    if os.environ.get("TSF_AUTH_PASS") or os.environ.get("TSF_AUTH_SHA256"):
        return False, "密码由环境变量 TSF_AUTH_PASS 控制, 改文件不生效"
    if AUTH_ON and not pw_ok(old or ""):
        return False, "原密码不对"
    n = (new or "").strip()
    if len(n) < 6:
        return False, "新密码至少 6 位"
    if AUTH_ON and hmac.compare_digest(n.encode(), (AUTH_PASS or "").encode()):
        return False, "新密码不能和原密码一样"
    try:
        with open(AUTH_FILE, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    newsec = hashlib.sha256(os.urandom(32)).hexdigest()
    out, has_pass, has_sec = [], False, False
    for ln in lines:
        s = ln.strip()
        k = s.split("=", 1)[0].strip().lower() if ("=" in s and not s.startswith("#")) else ""
        if k == "pass":
            out.append("pass=" + n)
            has_pass = True
        elif k == "sha256":
            continue                       # 老写法统一换成 pass=
        elif k == "secret":
            out.append("secret=" + newsec)
            has_sec = True
        else:
            out.append(ln)
    if not has_pass:
        out.append("pass=" + n)
    if not has_sec:
        out.append("secret=" + newsec)
    try:
        os.makedirs(os.path.dirname(AUTH_FILE) or ".", exist_ok=True)
        tmp = AUTH_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, AUTH_FILE)
    except OSError as ex:
        return False, "写入失败: %s" % str(ex)[:80]
    AUTH_PASS, AUTH_SHA, AUTH_SECRET, AUTH_ON = n, "", newsec, True
    return True, "密码已更新, 其它设备需要重新登录"


def sess_token(exp):
    raw = "%s|%d" % (AUTH_USER, exp)
    sig = hmac.new(AUTH_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    return "%d.%s" % (exp, sig)


def sess_ok(tok):
    try:
        exp = int(tok.split(".", 1)[0])
    except (ValueError, AttributeError):
        return False
    if exp < time.time():
        return False
    return hmac.compare_digest(tok, sess_token(exp))


def fail_check(ip, inc):
    """同一 IP 10 分钟内连错 8 次就锁 5 分钟, 防爆破"""
    now = time.time()
    with FAIL_LOCK:
        cnt, t0 = FAILS.get(ip, [0, now])
        if now - t0 > 600:
            cnt, t0 = 0, now
        if inc:
            cnt += 1
        FAILS[ip] = [cnt, t0]
        return cnt >= 8


LOGIN_HTML = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>__L_LOGIN__ · __L_BRAND__</title>
<style>
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
 background:#0d1219;color:#e8eef4;font:15px/1.5 -apple-system,"SF Pro Text","PingFang SC","Microsoft YaHei",sans-serif;
 padding:24px}
.card{width:100%;max-width:340px;background:#161d26;border:1px solid #232c36;border-radius:18px;
 padding:26px 22px 22px;box-shadow:0 18px 50px rgba(0,0,0,.45)}
.logo{display:flex;align-items:center;gap:10px;margin-bottom:18px}
.dot{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#10b981,#059669);
 display:flex;align-items:center;justify-content:center;font-size:17px}
img.dot{object-fit:cover;padding:0;background:none;border-radius:50%}
h1{font-size:16px;margin:0;font-weight:600;letter-spacing:.2px}
p.sub{margin:2px 0 0;font-size:12px;color:#7d8894}
label{display:block;font-size:12px;color:#97a3af;margin:12px 0 6px}
input{width:100%;padding:11px 12px;border-radius:11px;border:1px solid #2b3540;background:#0f151d;
 color:#e8eef4;font-size:15px;outline:none}
input:focus{border-color:#10b981;box-shadow:0 0 0 3px rgba(16,185,129,.15)}
button{width:100%;margin-top:18px;padding:12px;border:0;border-radius:11px;cursor:pointer;
 background:#10b981;color:#fff;font-size:15px;font-weight:600}
button:active{background:#0ea472}
.err{margin-top:12px;font-size:13px;color:#f87171;min-height:18px}
.foot{margin-top:16px;font-size:11px;color:#5f6b78;text-align:center}
</style></head><body>
<form class="card" method="post" action="/login">
  <div class="logo"><img class="dot" src="/api/brand/logo" alt="">
    <div><h1>__L_BRAND__</h1><p class="sub">TSL Sentry Drive</p></div></div>
  <label>__L_USER__</label>
  <input name="u" autocomplete="username" autocapitalize="none" autocorrect="off" value="__USER__">
  <label>__L_PASS__</label>
  <input name="p" type="password" autocomplete="current-password" autofocus>
  <input type="hidden" name="next" value="__NEXT__">
  <button type="submit">__L_LOGIN__</button>
  <div class="err">__MSG__</div>
  <div class="foot">__L_FOOT__</div>
</form></body></html>"""


class Handler(BaseHTTPRequestHandler):
    timeout = SOCK_TIMEOUT   # 慢连接/半包请求超时断开, 避免长期占用线程

    def log_message(self, fmt, *args):
        pass

    # ---- 认证 ----
    def _cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    def _cookie_secure(self):
        """只有走 HTTPS (反代传 X-Forwarded-Proto 或显式开启) 才加 Secure;
        纯 HTTP 直连加了会导致浏览器不回传 cookie、谁都登录不上。"""
        if os.environ.get("TSF_COOKIE_SECURE") == "1":
            return "; Secure"
        if (self.headers.get("X-Forwarded-Proto") or "").strip().lower() == "https":
            return "; Secure"
        return ""

    def _authed(self):
        if not AUTH_ON:
            return True
        if sess_ok(self._cookie("tsf_sess")):
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            ip = self.client_address[0] if self.client_address else "?"
            if fail_check(ip, False):        # 与登录页共用限速: 锁定期不再校验密码
                return False
            try:
                u, _, p = base64.b64decode(h[6:]).decode("utf-8", "replace").partition(":")
            except Exception:
                fail_check(ip, True)
                return False
            if hmac.compare_digest(u.encode(), AUTH_USER.encode()) and pw_ok(p):
                with FAIL_LOCK:
                    FAILS.pop(ip, None)
                return True
            fail_check(ip, True)
            return False
        return False

    def _login_page(self, msg="", nxt="/", code=200):
        lang = "zh"
        days = str(max(1, AUTH_TTL // 86400))
        foot = tr("仅限本人访问", lang) + " · " + tr("登录状态保留", lang) + " " + days + " " + tr("天", lang)
        html = (LOGIN_HTML.replace("__USER__", AUTH_USER)
                .replace("__NEXT__", nxt.replace('"', "&quot;"))
                .replace("__MSG__", tr(msg, lang))
                .replace("__L_BRAND__", (brand_name() or BRAND_NAME_DEFAULT)
                 .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
                .replace("__L_USER__", tr("用户名", lang))
                .replace("__L_PASS__", tr("密码", lang))
                .replace("__L_LOGIN__", tr("登录", lang))
                .replace("__L_FOOT__", foot))
        if lang != "zh":
            html = html.replace('<html lang="zh">', '<html lang="%s">' % lang)
        self._send(code, html.encode())

    def _do_login(self):
        n = min(int(self.headers.get("Content-Length") or 0), 4096)
        try:
            f = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "ignore"))
        except Exception:
            f = {}
        nxt = (f.get("next", ["/"])[0] or "/")
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/"
        ip = self.client_address[0] if self.client_address else "?"
        if fail_check(ip, False):
            self._login_page("尝试次数过多，请 5 分钟后再试", nxt, 429)
            return
        if f.get("u", [""])[0] == AUTH_USER and pw_ok(f.get("p", [""])[0]):
            fail_check(ip, False)
            with FAIL_LOCK:
                FAILS.pop(ip, None)
            exp = int(time.time()) + AUTH_TTL
            self.send_response(302)
            self.send_header("Location", nxt)
            self.send_header("Set-Cookie",
                             "tsf_sess=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax%s"
                             % (sess_token(exp), AUTH_TTL, self._cookie_secure()))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        fail_check(ip, True)
        time.sleep(0.4)          # 轻微延迟, 拖慢暴力破解
        self._login_page("用户名或密码不对", nxt, 401)

    def _gate(self):
        """未登录: 页面跳登录页, 媒体/接口直接 401。返回 True 表示可继续"""
        if not AUTH_ON:
            return True
        p = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if p in ("/login", "/logout", "/api/brand/logo"):
            return True
        if self._authed():
            return True
        if p in ("/", "/index.html") or "text/html" in (self.headers.get("Accept") or ""):
            self.send_response(302)
            self.send_header("Location", "/login?next=" + urllib.parse.quote(self.path or "/"))
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._send(401, "unauthorized".encode(), "text/plain; charset=utf-8")
        return False

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # 页面/接口一律禁止缓存: 之前 HTML 没有任何缓存头, iOS Safari 会把旧页面留在内存里,
        # 升级后手机上仍然显示旧界面 (典型症状: 已经改了样式, 手机上还是老样子)
        if "text/html" in ctype or "application/json" in ctype:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

    def _read_json(self, limit=MAX_JSON):
        """读 JSON 请求体: 超过上限返回 "TOOBIG", 解析失败返回 None, 空体返回 {}。
        不用裸 rfile.read(Content-Length), 免得一个大包把 1.4G 内存吃满。"""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return None
        if n > limit:
            return "TOOBIG"
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8", "ignore") or "{}")
        except Exception:
            return None

    def _read_upload(self):
        """解析 multipart: 返回 (文件名, 文件数据, 普通字段dict)"""
        ctype = self.headers.get("Content-Type", "")
        mm = re.search(r'boundary=([^;]+)', ctype)
        if "multipart/form-data" not in ctype or not mm:
            return None, None, {}
        boundary = mm.group(1).strip('"').encode()
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_UPLOAD:
            return "TOOBIG", None, {}
        body = self.rfile.read(length)
        fields = {}
        file_fn = None
        file_data = None
        for part in body.split(b"--" + boundary):
            i = part.find(b"\r\n\r\n")
            if i == -1:
                continue
            headers = part[:i].decode("utf-8", "replace")
            data = part[i + 4:]
            if data.endswith(b"\r\n"):
                data = data[:-2]
            nm = re.search(r'name="([^"]*)"', headers)
            if 'filename="' in headers:
                fn = re.search(r'filename="([^"]*)"', headers)
                if fn and fn.group(1) and data:
                    file_fn, file_data = fn.group(1), data
            elif nm and nm.group(1):
                fields[nm.group(1)] = data.decode("utf-8", "replace").strip()
        return file_fn, file_data, fields

    def do_HEAD(self):
        """只回头部: iOS/安卓下载器在真正下载前常先 HEAD 探大小, 不支持会退化成"边播边存"的残缺文件"""
        def hdr_only(code, extra=None):
            self.send_response(code)
            for k, v in (extra or []):
                self.send_header(k, v)
            self.send_header("Content-Length", "0")
            self.end_headers()

        if not self._gate():
            return
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path == "/dl":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            fp = safe_archive_path(q.get("path", [""])[0])
            if not fp:
                hdr_only(404)
                return
            out = fp
            qv = q.get("q", [""])[0]
            if qv in RES_SCALE:
                out = get_variant(fp, qv)
            serve_file(self, out, head_only=True)
            return
        m = re.match(r"^/media/([\w-]+)/([\w\-. ]+)/([\w\-. ]+)$", path)
        if m:
            fp = os.path.normpath(os.path.join(ARCHIVE, m.group(1), m.group(2), m.group(3)))
            if not fp.startswith(ARCHIVE) or not os.path.isfile(fp):
                hdr_only(404)
                return
            try:
                size = str(os.path.getsize(fp))
            except OSError:
                hdr_only(404)
                return
            hdr_only(200, [("Content-Type", "video/mp4"), ("Content-Length", size),
                           ("Accept-Ranges", "bytes")])
            return
        if path.startswith("/api/export/"):
            hdr_only(200, [("Content-Type", "video/mp4"), ("Accept-Ranges", "bytes")])
            return
        hdr_only(405)

    def do_GET(self):
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path == "/login":
            if not AUTH_ON:
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            self._login_page("", q.get("next", ["/"])[0])
            return
        if path == "/logout":
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", "tsf_sess=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax%s" % self._cookie_secure())
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/api/ver":
            # 版本探针: 前端刷新时对比, 服务端升级了就自动重载, 不用手动清缓存
            body = json.dumps({"v": APP_VERSION}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(body)
            return
        if not self._gate():
            return
        if path in ("/", "/index.html"):
            html = (HTML.replace("__CAT_NAMES__", json.dumps(CAT_NAMES, ensure_ascii=False))
                    .replace("__I18N__", I18N_JS).replace("__LANGS__", LANG_JS)
                    .replace("__APP_VER__", APP_VERSION))
            self._send(200, html.encode())
            return
        elif path == "/api/fan":
            self._json(fan_state())
        elif path == "/api/net":
            self._json(net_state())
        elif path == "/api/stitch/status":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            job = STITCH_JOBS.get(q.get("id", [""])[0])
            if not job:
                self._json({"state": "error", "err": "任务不存在或已过期"}, 404)
                return
            self._json({"state": job["state"], "pct": job.get("pct", 0),
                        "err": job.get("err", ""), "size": job.get("size", 0)})
        elif path == "/api/stitch/dl":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            jid = q.get("id", [""])[0]
            job = STITCH_JOBS.get(jid)
            if not job or job.get("state") != "done" or not os.path.isfile(job.get("path") or ""):
                self._send(404, b"not ready")
                return
            fp = job["path"]
            fname = job.get("name") or "stitch.mp4"
            size = os.path.getsize(fp)
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % urllib.parse.quote(fname))
            self.end_headers()
            with open(fp, "rb") as f:
                while True:
                    chunk = f.read(262144)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            with STITCH_LOCK:
                STITCH_JOBS.pop(jid, None)
            try:
                os.unlink(fp)
            except OSError:
                pass
        elif path == "/api/export/burn/dl":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            jid = q.get("id", [""])[0]
            job = STITCH_JOBS.get(jid)
            if not job or job.get("state") != "done" or not os.path.isfile(job.get("path") or ""):
                self._send(404, b"not ready")
                return
            fp = job["path"]
            fname = job.get("name") or "teslacam.mp4"
            try:
                size = os.path.getsize(fp)
            except OSError:
                self._send(404, b"gone")
                return
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            # ASCII 兜底文件名 + UTF-8 原名: iOS 下载器对百分号编码的中文名会显示成乱码
            self.send_header("Content-Disposition",
                             'attachment; filename="teslacam.mp4"; filename*=UTF-8\'\'%s'
                             % urllib.parse.quote(fname))
            self.end_headers()
            try:
                with open(fp, "rb") as f:
                    while True:
                        chunk = f.read(262144)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                return
            with STITCH_LOCK:
                STITCH_JOBS.pop(jid, None)
            try:
                os.unlink(fp)
            except OSError:
                pass
        elif path == "/api/events":
            self._json(list_events())
        elif path == "/api/live/status":
            folder, newest = live_latest()
            self._json({"ok": True, "folder": folder,
                        "age": round(newest - time.time(), 1) if newest else -1,
                        "car_age": round(usb_img_age(), 1)})
        elif path == "/api/telemetry":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            p = q.get("path", [""])[0]
            fp = safe_archive_dir(p) if p else None
            if not fp or not os.path.isfile(fp):
                self._json({"ok": False, "reason": "bad-path"}, 404)
                return
            tel = telemetry_cached(fp)
            if not tel:
                self._json({"ok": False, "reason": "no-sei"})
                return
            self._json({"ok": True, **tel})
        elif path == "/api/live":
            self._json(live_status())
        elif path == "/api/auth/info":
            self._json({"user": AUTH_USER, "on": AUTH_ON})
        elif path == "/api/notify":
            self._json(notify_status())
        elif path == "/api/ota/check":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            self._json(ota_check(force=q.get("force", ["0"])[0] == "1"))
        elif path == "/api/settings":
            self._json({"ok": True, "auto_update": load_settings().get("auto_update", True),
                        "ui_style": load_settings().get("ui_style", "default"),
                        "brand_name": brand_name(), "brand_default": BRAND_NAME_DEFAULT,
                        "brand_logo": load_settings().get("brand_logo", ""),
                        "brand_logo_v": brand_logo_ver(),
                        "auto_checked": AUTO_UPD["last_check"], "auto_msg": AUTO_UPD["last_result"]})
        elif path == "/api/font":
            fp = _wm_font()
            self._json({"ok": bool(fp), "path": fp, "name": os.path.basename(fp) if fp else "",
                        "size": os.path.getsize(fp) if fp else 0,
                        "dir": os.path.dirname(fp) if fp else FONT_DIR,
                        "install_dir": FONT_DIR})
        elif path == "/api/prewarm":
            # 480p 预热进度 (调试/自检用): done=累计转好路数, last=最近做的事件
            self._json({"on": PREWARM["on"], "done": PREWARM["done"], "last": PREWARM["last"],
                        "q": PREWARM_Q, "busy_users": USER_TRANS[0],
                        "media_active": MEDIA_ACTIVE[0]})
        elif path == "/api/brand/logo":
            data, ct = brand_logo_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(data)))
            # 图标不大 (默认 10KB), 允许缓存省流量; 换图后前端会带 ?v= 破缓存
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(data)
        elif path == "/api/skins":
            skins = [] if not storage_ready() else sorted(
                f for f in os.listdir(SKIN_DIR)
                if f != "active.json" and os.path.isfile(os.path.join(SKIN_DIR, f)))
            self._json({"skins": skins, "active": active_skin() if storage_ready() else None})
        elif path == "/api/skin":
            s = active_skin()
            if s and s.endswith(".css") and os.path.isfile(os.path.join(SKIN_DIR, s)):
                with open(os.path.join(SKIN_DIR, s), "rb") as f:
                    self._send(200, f.read(), "text/css; charset=utf-8")
            else:
                self._send(204, b"", "text/css")
        elif path.startswith("/skin-media/"):
            fn = safe_name(path[len("/skin-media/"):])
            fp = os.path.join(SKIN_DIR, fn) if fn else ""
            if fn and os.path.isfile(fp):
                ext = fn.rsplit(".", 1)[-1].lower()
                ct = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                      "webp": "image/webp", "css": "text/css"}.get(ext, "application/octet-stream")
                with open(fp, "rb") as f:
                    self._send(200, f.read(), ct)
            else:
                self._send(404, b"not found")
        elif path == "/api/audio":
            if not storage_ready():
                self._json({"queue": [], "done": []})
                return
            q = sorted(f for f in os.listdir(AUDIO_Q) if os.path.isfile(os.path.join(AUDIO_Q, f)))
            d = sorted(f for f in os.listdir(AUDIO_DONE) if os.path.isfile(os.path.join(AUDIO_DONE, f)))
            self._json({"queue": q, "done": d})
        elif path == "/api/browse":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            d = safe_archive_dir(q.get("dir", [""])[0])
            if not d or not os.path.isdir(d):
                self._json({"ok": False, "msg": "目录不存在或不在 /archive 内"}, 404)
                return
            dirs, files = [], []
            for e in sorted(os.listdir(d)):
                ep = os.path.join(d, e)
                if os.path.isdir(ep):
                    dirs.append(e)
                elif os.path.isfile(ep):
                    files.append({"name": e, "size": os.path.getsize(ep)})
            self._json({"ok": True, "dir": _unmap_archive(d), "dirs": dirs, "files": files})
        elif path == "/api/storage/status":
            self._json(storage_status())
        elif path == "/api/usb/browse":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            fp = usb_real(q.get("dir", [""])[0])
            if not usb_attached or not os.path.ismount(MNT):
                self._json({"ok": False, "attached": False, "msg": "车机U盘未连接"})
                return
            if fp is None or not os.path.isdir(fp):
                self._json({"ok": False, "attached": True, "msg": "目录不存在"}, 404)
                return
            dirs, files = [], []
            for e in sorted(os.listdir(fp)):
                ep = os.path.join(fp, e)
                if os.path.isdir(ep):
                    dirs.append(e)
                elif os.path.isfile(ep):
                    files.append({"name": e, "size": os.path.getsize(ep)})
            rel = os.path.relpath(fp, MNT).replace("\\", "/")
            self._json({"ok": True, "attached": True, "dir": "" if rel == "." else rel,
                        "dirs": dirs, "files": files})
        elif path == "/usbdl":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            fp = usb_real(q.get("path", [""])[0])
            if not fp or not os.path.isfile(fp):
                self._send(404, b"not found")
                return
            serve_file(self, fp)
        elif path == "/dl":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            fp = safe_archive_path(q.get("path", [""])[0])
            if not fp:
                self._send(404, b"not found")
                return
            out = fp
            qv = q.get("q", [""])[0]
            if qv in RES_SCALE:  # 下载也支持清晰度: 转码缓存副本, 失败回退原文件
                out = get_variant(fp, qv)
            serve_file(self, out)
        elif path.startswith("/api/export/"):
            m2 = re.match(r"^/api/export/([\w-]+)/([\w\-. ]+)/?$", path)
            if not m2:
                self._send(404, b"not found")
                return
            q2 = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            cams = [c.strip() for c in (q2.get("cams", [""])[0] or "").split(",") if c.strip()]
            evdir = safe_archive_dir(ARCHIVE + "/" + m2.group(1) + "/" + m2.group(2))
            if not evdir or not os.path.isdir(evdir):
                self._send(404, b"not found")
                return
            vids = []
            allf = latest_group(sorted(f for f in os.listdir(evdir) if f.endswith(".mp4")))
            for f in allf:
                cam = f.rsplit("-", 1)[-1][:-4] if "-" in f else f
                if not cams or cam in cams:
                    vids.append(f)
            if not vids:
                self._send(404, b"no matching videos")
                return
            evname = m2.group(2)
            zname = evname + (("_" + "-".join(cams)) if cams and len(cams) < 6 else "") + ".zip"
            qv = q2.get("q", [""])[0]  # 打包zip也支持清晰度: 每路先取转码副本 (串行转码), 失败回退原文件
            if qv not in RES_SCALE:
                qv = ""
            tmp = tempfile.NamedTemporaryFile(prefix="exp_", suffix=".zip", delete=False)
            tmp.close()
            try:
                with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_STORED) as z:
                    for f in vids:
                        ffp = os.path.join(evdir, f)
                        if qv:
                            ffp = get_variant(ffp, qv)
                        z.write(ffp, arcname=evname + "/" + f)
                    ej = os.path.join(evdir, "event.json")
                    if os.path.isfile(ej):
                        z.write(ej, arcname=evname + "/event.json")
                zsize = os.path.getsize(tmp.name)
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(zsize))
                self.send_header("Content-Disposition",
                                 'attachment; filename="%s"' % urllib.parse.quote(zname))
                self.end_headers()
                with open(tmp.name, "rb") as zf:
                    while True:
                        chunk = zf.read(262144)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
        elif path.startswith("/thumb/"):
            self._serve_thumb(path)
        else:
            m = re.match(r"^/media/([\w-]+)/([\w\-. ]+)/([\w\-. ]+)$", path)
            if not m:
                self._send(404, b"not found")
                return
            fp = os.path.normpath(os.path.join(ARCHIVE, m.group(1), m.group(2), m.group(3)))
            if not fp.startswith(ARCHIVE) or not os.path.isfile(fp):
                self._send(404, b"not found")
                return
            # 清晰度: ?q=360p/480p/720p 返回缓存副本; ?preview=10 优先取前10秒预缓冲。
            # sid 绑定播放器会话, 退出后服务端取消该会话的完整转码。
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            qv = qs.get("q", ["orig"])[0]
            sid = qs.get("sid", [""])[0]
            want_preview = qs.get("preview", ["0"])[0] == "10"
            variant_note = ""
            if qv in RES_SCALE and qv != "orig":
                if sid:
                    playback_beat(sid, [fp], qv)
                if want_preview:
                    if _variant_ready(fp, qv):
                        fp = _variant_path(fp, qv)
                    elif _variant_ready(fp, qv, 10):
                        fp = _variant_path(fp, qv, 10)
                        variant_note = "preview10"
                    else:
                        spawn_variant(fp, qv, owner=sid or None, seconds=10)
                        alt = next((a for a in ("480p", "360p", "720p")
                                    if a != qv and _variant_ready(fp, a)), None)
                        if alt:
                            fp = _variant_path(fp, alt)
                            variant_note = "alt:" + alt
                        else:
                            variant_note = "orig"
                elif _variant_ready(fp, qv):
                    fp = _variant_path(fp, qv)
                else:
                    spawn_variant(fp, qv, owner=sid or None)
                    alt = next((a for a in ("480p", "360p", "720p")
                                if a != qv and _variant_ready(fp, a)), None)
                    if alt:
                        fp = _variant_path(fp, alt)
                        variant_note = "alt:" + alt
                    else:
                        variant_note = "orig"
            size = os.path.getsize(fp)
            rng = self.headers.get("Range")
            if rng:
                # 支持三种形式: bytes=a-b / bytes=a- / bytes=-n (尾部 n 字节)
                mm2 = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
                if not mm2:
                    self._send(416, b"bad range")
                    return
                s1, s2 = mm2.group(1), mm2.group(2)
                if s1 == "":
                    # 尾部范围: 浏览器读 mp4 moov 时常用, 不支持会让视频一直卡在 readyState 0
                    n = int(s2 or 0)
                    start = max(0, size - n)
                    end = size - 1
                else:
                    start = int(s1)
                    end = int(s2) if s2 else size - 1
                if start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                if end < start:
                    end = size - 1
            else:
                start, end = 0, size - 1
            length = end - start + 1
            # 并发限流: 浏览器一次会为几十个缩略图发请求, 不限流会把设备拖死
            if not MEDIA_SEM.acquire(timeout=20):
                self._send(503, b"busy")
                return
            MEDIA_ACTIVE[0] += 1
            try:
                self.send_response(206 if rng else 200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                if variant_note:
                    self.send_header("X-TSF-Variant", variant_note)   # 本次暂用替代档/原画, 后台正在转目标档
                if rng:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                # 写循环必须能感知「客户端已经不要这份数据了」:
                # 浏览器 preload=metadata 只读完 moov 就中止请求 (ERR_ABORTED), 而我们这边
                # 还在傻写剩下的几 MB —— 线程挂死、MEDIA_SEM 名额被占光, 后面用户点播放的
                # seek 请求全部排队等 20 秒超时 503, 四格画面就永远停在「缓冲中…」。
                # select 探到对端 EOF/RST 立刻收摊; 5s socket 超时兜底 (公网 64KB 正常
                # 几百毫秒就写完; 某些中转链路不转发 RST, 客户端 abort 后服务端
                # 会一直往黑洞里写满 15 秒, 把上行占死, 后面 seek 的请求就饿着)。
                # 超时只作用于「单次 write 卡住」, 正常下载大文件每块都很快, 不受影响。
                try:
                    self.connection.settimeout(5)
                except OSError:
                    pass
                peer_dead = False
                with open(fp, "rb") as f:
                    f.seek(start)
                    remain = length
                    deadline = time.time() + 60
                    while remain > 0:
                        try:
                            r, _, _ = select.select([self.connection], [], [], 0)
                            if r:
                                if not self.connection.recv(1, socket.MSG_PEEK):
                                    peer_dead = True     # 对端 FIN
                                    break
                        except (ConnectionResetError, OSError):
                            peer_dead = True
                            break
                        chunk = f.read(min(65536, remain))
                        if not chunk:
                            break
                        try:
                            self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError, socket.timeout, TimeoutError, OSError):
                            peer_dead = True
                            break
                        remain -= len(chunk)
                        if time.time() > deadline:
                            break     # 链路太慢, 交还线程给别的请求
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                MEDIA_ACTIVE[0] = max(0, MEDIA_ACTIVE[0] - 1)
                MEDIA_SEM.release()

    def _serve_thumb(self, path):
        """列表缩略图: 用 ffmpeg 抽指定秒数一帧 (?t=秒, 默认 1), 结果按 (路径+大小+mtime+t) 哈希缓存在 eMMC"""
        parts = path[len("/thumb/"):].split("/")
        if len(parts) != 3:
            self._send(404, b"not found")
            return
        cat, name, fn = [urllib.parse.unquote(p) for p in parts]
        evdir = safe_archive_dir(os.path.join(ARCHIVE, cat, name))
        fn = safe_name(fn)
        if not evdir or not fn:
            self._send(404, b"not found")
            return
        fp = os.path.join(evdir, fn)
        if not os.path.isfile(fp):
            self._send(404, b"not found")
            return
        try:
            st = os.stat(fp)
        except OSError:
            self._send(404, b"not found")
            return
        try:
            ss_t = max(0.0, min(float(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("t", ["1"])[0]), 3600.0))
        except ValueError:
            ss_t = 1.0
        out = thumb_file(fp, ss_t)
        if not out:
            self._send(404, b"no thumb")
            return
        try:
            with open(out, "rb") as f:
                data = f.read()
        except OSError:
            self._send(404, b"not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=604800")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        p = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if p == "/login" and AUTH_ON:
            self._do_login()
            return
        if not self._gate():
            return
        if not storage_ready() and p in {
                "/api/fm", "/api/kick", "/api/export/burn", "/api/stitch",
                "/api/upload/skin", "/api/upload/audio", "/api/upload/usb", "/api/upload/file",
                "/api/skin/activate", "/api/audio/setlockchime", "/api/usb/attach", "/api/usb/detach"}:
            self._json({"ok": False, "msg": "外接存储未挂载，当前仅可使用存储管理功能"}, 503)
            return
        path = urllib.parse.unquote(self.path)
        if p == "/api/fm":
            body = self._read_json()
            if body == "TOOBIG":
                self._json({"ok": False, "msg": "请求体过大 (上限 1MB)"}, 413)
                return
            if not isinstance(body, dict):
                self._json({"ok": False, "msg": "参数错误"}, 400)
                return
            try:
                ok, msg, done, failed, extra = fm_action(
                    str(body.get("area") or ""), str(body.get("op") or ""),
                    body.get("items") or [], body.get("dest") or "", body.get("name") or "")
            except Exception as ex:
                self._json({"ok": False, "msg": "操作失败: %s" % ex}, 500)
                return
            j = {"ok": ok, "msg": msg, "done": done, "failed": failed}
            j.update(extra)
            self._json(j)
            return
        if path == "/api/kick":
            # 前端播到当前段一半/打开事件时, 让服务端把相邻段的当前清晰度先转好。
            # 走 get_variant(slot=True) → 计入 USER_TRANS, 预热线程自动让位;
            # Q_SEM(并发2)串住所有转码, 不会把设备打死。已转好的直接跳过。
            body = self._read_json()
            if body == "TOOBIG":
                self._json({"ok": False, "msg": "请求体过大"}, 413)
                return
            if not isinstance(body, dict):
                body = {}
            qv = str(body.get("q") or "")
            sid = str(body.get("sid") or "")
            paths = body.get("paths") if isinstance(body.get("paths"), list) else []
            started, skipped = 0, 0
            if qv in RES_SCALE:
                if sid:
                    playback_beat(sid, [], qv)
                for p in paths[:10]:
                    if not isinstance(p, str):
                        skipped += 1
                        continue
                    # 前端发来的是媒体 URL /media/{cat}/{name}/{file}, 归一映射回归档路径
                    fp = urllib.parse.unquote(p).split("?")[0]
                    if fp.startswith("/media/"):
                        fp = fp[len("/media"):]          # -> /SentryClips/...
                    fp = os.path.normpath(fp)
                    if not fp.startswith(ARCHIVE + os.sep):
                        fp = os.path.normpath(os.path.join(ARCHIVE, fp.lstrip("/")))
                    if not fp.startswith(ARCHIVE + os.sep) or not fp.endswith(".mp4") \
                            or not os.path.isfile(fp):
                        skipped += 1
                        continue
                    # 预转白名单: 只有哨兵 / 手动保存。行车记录片段滚动淘汰, 预转的缓存
                    # 马上作废, 只会让设备持续满载转码; 在服务端兜住, 旧版页面缓存也拦得住。
                    # 注意: 只管「提前预转」, 用户真点开时 /media 的按需转码不受影响。
                    rel = os.path.relpath(fp, ARCHIVE).replace(os.sep, "/")
                    if not rel.startswith(("SentryClips/", "SavedClips/")):
                        skipped += 1
                        continue
                    if _variant_ready(fp, qv):
                        skipped += 1
                        continue
                    # 后台排队生成, 同一个文件只排一次; 请求立刻返回, 不占用连接
                    if spawn_variant(fp, qv, owner=sid or None):
                        started += 1
                    else:
                        skipped += 1
            self._json({"ok": True, "started": started, "skipped": skipped})
            return
        if path == "/api/playback/beat":
            body = self._read_json()
            if not isinstance(body, dict):
                body = {}
            sid = str(body.get("sid") or "")[:64]
            q = str(body.get("q") or "")
            paths = body.get("paths") if isinstance(body.get("paths"), list) else []
            playback_beat(sid, [str(p) for p in paths[:20]], q)
            self._json({"ok": True})
            return
        if path == "/api/playback/leave":
            body = self._read_json()
            if not isinstance(body, dict):
                body = {}
            playback_leave(str(body.get("sid") or "")[:64])
            self._json({"ok": True})
            return
        if path == "/api/auth/pass":
            body = self._read_json()
            if body == "TOOBIG":
                self._json({"ok": False, "msg": "请求体过大 (上限 1MB)"}, 413)
                return
            if not isinstance(body, dict):
                self._json({"ok": False, "msg": "参数错误"}, 400)
                return
            ok, msg = auth_set_pass(str(body.get("old") or ""), str(body.get("new") or ""))
            self._json({"ok": ok, "msg": msg, "user": AUTH_USER})
            return
        if path == "/api/notify/save":
            body = self._read_json()
            if body == "TOOBIG":
                self._json({"ok": False, "msg": "请求体过大 (上限 1MB)"}, 413)
                return
            if not isinstance(body, dict):
                self._json({"ok": False, "msg": "参数错误"}, 400)
                return
            patch = {}
            for k in ("enabled", "saved"):
                if k in body:
                    patch[k] = bool(body.get(k))
            for k in ("mode", "media", "quality", "webhook", "app_id", "receive_id",
                      "receive_id_type", "public_url"):
                if k in body:
                    patch[k] = str(body.get(k) or "").strip()
            if str(body.get("app_secret") or "").strip():
                patch["app_secret"] = str(body["app_secret"]).strip()
            if "delay" in body:
                try:
                    patch["delay"] = max(5, min(600, int(body["delay"])))
                except (TypeError, ValueError):
                    pass
            if "vdur" in body:
                try:
                    patch["vdur"] = max(10, min(60, int(body["vdur"])))
                except (TypeError, ValueError):
                    pass
            if str(patch.get("quality") or "") not in ("360p", "480p", "720p"):
                patch.pop("quality", None)
            if str(patch.get("media") or "") not in ("thumb", "video"):
                patch.pop("media", None)
            conf = notify_save(patch)
            if _dm_ready(conf):
                warn = "" if (conf.get("public_url") or "").strip() else "私聊已可用; 填「查看链接前缀」后卡片上会有查看按钮"
            elif str(conf.get("webhook") or "").strip():
                warn = "私聊未就绪 (需 App ID/Secret + 接收人), 当前会推到群里"
            else:
                warn = "还没配接收人: 私聊需要 App ID/Secret + 接收人, 或填群机器人 webhook"
            self._json({"ok": True, "msg": "已保存", "status": notify_status(), "warn": warn})
            return
        if path == "/api/notify/test":
            cat, name = "SentryClips", ""
            try:
                base = os.path.join(ARCHIVE, "SentryClips")
                cands = sorted(e for e in os.listdir(base)
                               if re.match(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$", e))
                name = cands[-1] if cands else ""
            except OSError:
                pass
            if not name:
                self._json({"ok": False, "msg": "归档里还没有哨兵事件, 无法生成测试卡片"}, 400)
                return
            ok, msg = notify_push(cat, name, test=True)
            self._json({"ok": ok, "msg": msg})
            return
        if urllib.parse.urlsplit(self.path).path == "/api/push/upload":
            # 手动推送: 浏览器本机合成的片段 (webm/mp4 裸流) 上传到设备, 转码后推飞书私聊
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            cat = q.get("cat", [""])[0]
            name = q.get("name", [""])[0]
            quality = q.get("q", ["480p"])[0]
            if quality not in ("360p", "480p", "720p", "orig"):
                quality = "480p"
            length = int(self.headers.get("Content-Length", 0) or 0)
            if not name or not re.match(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$", name):
                self._json({"ok": False, "msg": "参数错误"}, 400)
                return
            if length <= 0 or length > 300 * 1048576:
                self._json({"ok": False, "msg": "片段为空或超过 300MB"}, 400)
                return
            evdir = safe_archive_dir(os.path.join(ARCHIVE, cat, name))
            if not evdir or not os.path.isdir(evdir):
                self._json({"ok": False, "msg": "事件不存在"}, 400)
                return
            tmp = "/tmp/tsf-push-upload.%d" % os.getpid()
            try:
                with open(tmp, "wb") as f:
                    rem = length
                    while rem > 0:
                        chunk = self.rfile.read(min(1 << 20, rem))
                        if not chunk:
                            break
                        f.write(chunk)
                        rem -= len(chunk)
                ok, msg = manual_push(notify_conf(), tmp, cat, name, quality)
            except Exception as ex:
                ok, msg = False, "推送失败: %s" % str(ex)[:160]
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            self._json({"ok": ok, "msg": msg})
            return
        if path == "/api/ota/apply":
            ok, msg = ota_apply()
            self._json({"ok": ok, "msg": msg})
            return
        if path == "/api/ota/rollback":
            ok, msg = ota_rollback()
            self._json({"ok": ok, "msg": msg})
            return
        if path == "/api/ui/style":
            body = self._read_json()
            if body == "TOOBIG" or not isinstance(body, dict):
                self._json({"ok": False, "msg": "参数错误"}, 400)
                return
            st = str(body.get("style") or "")
            if st not in ("default", "apple", "claude", "pixel"):
                self._json({"ok": False, "msg": "参数错误"}, 400)
                return
            save_settings({"ui_style": st})
            self._json({"ok": True, "style": st})
            return
        if path == "/api/ota/auto":
            body = self._read_json()
            if body == "TOOBIG" or not isinstance(body, dict):
                self._json({"ok": False, "msg": "参数错误"}, 400)
                return
            on = bool(body.get("on"))
            save_settings({"auto_update": on})
            if on:
                AUTO_UPD["next_try"] = 0        # 刚打开就尽快检查一次, 不用等下一轮
            self._json({"ok": True, "auto": on})
            return
        if path == "/api/font/dl":
            # 一键从官方 google/fonts 装中文字体 (17MB, 多镜像串行重试)
            if not FONT_LOCK.acquire(False):
                self._json({"ok": False, "msg": "字体正在安装中, 请稍等"}, 409)
                return
            try:
                ok, msg = _font_download()
            finally:
                FONT_LOCK.release()
            self._json({"ok": ok, "msg": msg}, 200 if ok else 500)
            return
        if path == "/api/font/upload":
            fn, data, _f = self._read_upload()
            if fn == "TOOBIG":
                self._json({"ok": False, "msg": "字体文件过大 (上限 100MB)"}, 413)
                return
            if not data or not fn or not str(fn).lower().endswith(FONT_EXTS):
                self._json({"ok": False, "msg": "仅支持 ttf / otf / ttc 字体文件"}, 400)
                return
            try:
                os.makedirs(FONT_DIR, exist_ok=True)
                base = safe_name(os.path.basename(str(fn))) or FONT_NAME
                if not base.lower().endswith(FONT_EXTS):
                    base = FONT_NAME
                dst = os.path.join(FONT_DIR, base)
                with open(dst + ".part", "wb") as f:
                    f.write(data)
                os.replace(dst + ".part", dst)
                if not _font_valid(dst):
                    os.unlink(dst)
                    self._json({"ok": False, "msg": "这不是有效的字体文件"}, 400)
                    return
                _font_reset()
                self._json({"ok": True, "msg": "字体已安装 (%.1fMB)" % (len(data) / 1048576.0)})
            except OSError as ex:
                self._json({"ok": False, "msg": "写入失败: %s" % ex}, 500)
            return
        if path == "/api/export/burn":
            body = self._read_json()
            if body == "TOOBIG":
                self._json({"ok": False, "error": "请求体过大 (上限 1MB)"}, 413)
                return
            if not isinstance(body, dict):
                self._json({"ok": False, "error": "参数错误"}, 400)
                return
            jid, err = start_export(body.get("cat") or "", body.get("name") or "",
                                    body.get("cams") or [], body.get("wm", True),
                                    body.get("q") or "720p", body.get("files"))
            if not jid:
                self._json({"ok": False, "error": err}, 400)
                return
            self._json({"ok": True, "id": jid})
            return
        if path == "/api/stitch":
            body = self._read_json()
            if body == "TOOBIG":
                self._json({"ok": False, "error": "请求体过大 (上限 1MB)"}, 413)
                return
            if not isinstance(body, dict):
                self._json({"ok": False, "error": "参数错误"}, 400)
                return
            jid, err = start_stitch(body.get("cat") or "", body.get("name") or "", body.get("cams") or [])
            if not jid:
                self._json({"ok": False, "error": err}, 400)
                return
            self._json({"ok": True, "id": jid})
            return
        if path == "/api/upload/skin":
            fn, data, _f = self._read_upload()
            if fn == "TOOBIG":
                self._json({"ok": False, "msg": "文件超过 3MB"}, 400)
                return
            fn = safe_name(fn)
            if not fn or not data or not fn.lower().endswith((".css", ".jpg", ".jpeg", ".png", ".webp")):
                self._json({"ok": False, "msg": "仅支持 css/jpg/png/webp"}, 400)
                return
            with open(os.path.join(SKIN_DIR, fn), "wb") as f:
                f.write(data)
            activated = False
            if fn.endswith(".css"):
                with open(os.path.join(SKIN_DIR, "active.json"), "w") as f:
                    json.dump({"skin": fn}, f)
                activated = True
            self._json({"ok": True, "msg": ("皮肤已上传并应用" if activated else "图片已上传, 请在 CSS 中用 /skin-media/" + fn), "activated": activated})
        elif path == "/api/brand/name":
            body = self._read_json()
            if body == "TOOBIG" or not isinstance(body, dict):
                self._json({"ok": False, "msg": "参数错误"}, 400)
                return
            nm = str(body.get("name") or "").strip()[:BRAND_NAME_MAX]
            nm = nm.replace("<", "").replace(">", "").replace("&", "").replace('"', "").replace("'", "")
            save_settings({"brand_name": nm})
            self._json({"ok": True, "name": nm or BRAND_NAME_DEFAULT})
        elif path == "/api/upload/brand-logo":
            fn, data, _f = self._read_upload()
            if fn == "TOOBIG":
                self._json({"ok": False, "msg": "文件超过 3MB"}, 400)
                return
            ext = os.path.splitext(fn or "")[1].lower()
            if ext == ".jpeg":
                ext = ".jpg"
            if not data or ext not in (".jpg", ".png", ".webp"):
                self._json({"ok": False, "msg": "仅支持 png/jpg/webp"}, 400)
                return
            try:
                os.makedirs(BRAND_DIR, exist_ok=True)
                brand_clear_files()          # 换格式时旧文件不能留着, 否则会两份并存
                with open(os.path.join(BRAND_DIR, "logo" + ext), "wb") as f:
                    f.write(data)
            except OSError as ex:
                self._json({"ok": False, "msg": "写入失败: %s" % ex}, 500)
                return
            save_settings({"brand_logo": "logo" + ext})
            self._json({"ok": True, "msg": "图标已更新", "logo": "logo" + ext})
        elif path == "/api/brand/reset":
            save_settings({"brand_name": "", "brand_logo": ""})
            brand_clear_files()
            self._json({"ok": True, "msg": "已恢复默认图标与名称"})
        elif path == "/api/upload/audio":
            fn, data, _f = self._read_upload()
            if fn == "TOOBIG":
                self._json({"ok": False, "msg": "文件超过 3MB (车机要求 <1MB)"}, 400)
                return
            fn = safe_name(fn)
            if not fn or not data or not fn.lower().endswith((".wav", ".mp3")):
                self._json({"ok": False, "msg": "仅支持 wav/mp3"}, 400)
                return
            if len(data) > 1024 * 1024:
                self._json({"ok": False, "msg": "车机要求单个音频 <1MB, 请裁剪后重试"}, 400)
                return
            with open(os.path.join(AUDIO_Q, fn), "wb") as f:
                f.write(data)
            self._json({"ok": True, "msg": "已加入队列, 归档同步时写入车机U盘"})
        elif path == "/api/storage/init":
            body = self._read_json()
            if body == "TOOBIG":
                self._json({"ok": False, "msg": "请求体过大"}, 413)
                return
            device = body.get("device") if isinstance(body, dict) else None
            percent = body.get("percent") if isinstance(body, dict) else None
            confirm = body.get("confirm") if isinstance(body, dict) else None
            ok, msg = storage_init(device, percent, confirm)
            if ok and msg.startswith("initialized:"):
                _tag, vg, ag = msg.split(":")
                msg = "已初始化: 虚拟U盘 %sG / 归档区 %sG, 页面即将刷新" % (vg, ag)
            self._json({"ok": ok, "msg": msg}, 200 if ok else 400)
        elif path == "/api/storage/format":
            body = self._read_json()
            if body == "TOOBIG":
                self._json({"ok": False, "msg": "请求体过大"}, 413)
                return
            device = body.get("device") if isinstance(body, dict) else None
            confirm = body.get("confirm") if isinstance(body, dict) else None
            ok, msg = storage_format(device, confirm)
            self._json({"ok": ok, "msg": msg}, 200 if ok else 400)
        elif path == "/api/storage/use":
            body = self._read_json()
            if body == "TOOBIG":
                self._json({"ok": False, "msg": "请求体过大"}, 413)
                return
            device = body.get("device") if isinstance(body, dict) else None
            ok, msg = storage_use(device)
            self._json({"ok": ok, "msg": ("已切换存储盘, 页面即将刷新" if msg == "switched" else "当前已是此盘") if ok else msg}, 200 if ok else 400)
        elif path == "/api/net/wired":
            body = self._read_json()
            if body == "TOOBIG" or not isinstance(body, dict):
                self._json({"ok": False, "msg": "请求体过大"}, 413)
                return
            ok, msg = net_wired_apply(body.get("mode"), body.get("ip", ""), body.get("prefix", "24"),
                                      body.get("gw", ""), body.get("dns") or [])
            self._json({"ok": ok, "msg": "有线设置已应用" if ok else msg}, 200 if ok else 400)
        elif path == "/api/net/wifi":
            body = self._read_json()
            if body == "TOOBIG" or not isinstance(body, dict):
                self._json({"ok": False, "msg": "请求体过大"}, 413)
                return
            ok, msg = net_wifi_apply(body.get("ssid", ""), body.get("psk", ""))
            self._json({"ok": ok, "msg": "无线连接已应用" if ok else msg}, 200 if ok else 400)
        elif path == "/api/net/wifi/scan":
            ok, msg, aps = net_wifi_scan()
            self._json({"ok": ok, "msg": msg, "aps": aps})
        elif path == "/api/net/wifi/forget":
            ok, msg = net_wifi_forget()
            self._json({"ok": ok, "msg": msg if not ok else "ok"})
        elif path == "/api/net/confirm":
            ok = net_confirm()
            self._json({"ok": True, "msg": "已确认连接, 回滚取消" if ok else "无待确认变更"})
        elif path == "/api/net/ap":
            body = self._read_json()
            if body == "TOOBIG" or not isinstance(body, dict):
                self._json({"ok": False, "msg": "请求体过大"}, 413)
                return
            ok, msg = ap_apply(str(body.get("enable", "0")), body.get("ssid", ""), body.get("psk", ""),
                               str(body.get("band", "auto")), str(body.get("channel_mode", "auto")),
                               body.get("channel", 0))
            self._json({"ok": ok, "msg": "热点设置已应用" if ok else msg}, 200 if ok else 400)
        elif path == "/api/net/bt":
            body = self._read_json()
            if body == "TOOBIG" or not isinstance(body, dict):
                self._json({"ok": False, "msg": "请求体过大"}, 413)
                return
            ok, msg = bt_apply(bool(body.get("power")), bool(body.get("discoverable")), body.get("name", ""))
            self._json({"ok": ok, "msg": "蓝牙设置已应用" if ok else msg}, 200 if ok else 400)
        elif path == "/api/net/bt/scan":
            ok, msg, devs = bt_scan()
            self._json({"ok": ok, "msg": msg, "devices": devs})
        elif path == "/api/net/bt/pair":
            body = self._read_json()
            if body == "TOOBIG" or not isinstance(body, dict):
                self._json({"ok": False, "msg": "请求体过大"}, 413)
                return
            ok, msg = bt_pair(body.get("mac", ""))
            self._json({"ok": ok, "msg": "配对完成" if ok else msg})
        elif path == "/api/net/bt/remove":
            body = self._read_json()
            if body == "TOOBIG" or not isinstance(body, dict):
                self._json({"ok": False, "msg": "请求体过大"}, 413)
                return
            ok, msg = bt_remove(body.get("mac", ""))
            self._json({"ok": ok, "msg": msg if not ok else "ok"})
        elif path == "/api/fan":
            body = self._read_json()
            if body == "TOOBIG" or not isinstance(body, dict):
                self._json({"ok": False, "msg": "请求体过大"}, 413)
                return
            ok, msg = fan_apply(body.get("mode", "auto"), body.get("manual", 50))
            self._json({"ok": ok, "msg": "风扇设置已保存, 立即生效" if ok else msg}, 200 if ok else 400)
        elif path == "/api/usb/attach":
            ok, msg = usb_attach()
            self._json({"ok": ok, "msg": "车机U盘已连接 (已临时断开车机读取, 5分钟无操作自动恢复)" if ok and msg != "already" else ("已处于管理状态" if ok else msg)})
        elif path == "/api/usb/detach":
            ok, msg = usb_detach()
            self._json({"ok": ok, "msg": "已恢复车机导出" if ok else msg})
        elif path == "/api/upload/usb":
            fn, data, fields = self._read_upload()
            if fn == "TOOBIG":
                self._json({"ok": False, "msg": "文件超过 100MB 上限"}, 400)
                return
            fn = safe_name(fn)
            if not fn or not data:
                self._json({"ok": False, "msg": "无效的文件"}, 400)
                return
            if not usb_attached or not os.path.ismount(MNT):
                self._json({"ok": False, "msg": "车机U盘未连接, 请先点「连接车机U盘」"}, 400)
                return
            dest = usb_real(fields.get("path"))
            if dest is None or not os.path.isdir(dest):
                self._json({"ok": False, "msg": "目标目录不存在"}, 400)
                return
            with open(os.path.join(dest, fn), "wb") as f:
                f.write(data)
            subprocess.run(["sync"], capture_output=True)
            rel = os.path.relpath(dest, MNT).replace("\\", "/")
            self._json({"ok": True, "msg": f"已上传到 U盘/{'' if rel == '.' else rel + '/' }{fn} ({len(data)//1024} KB)"})
        elif path == "/api/upload/file":
            fn, data, fields = self._read_upload()
            if fn == "TOOBIG":
                self._json({"ok": False, "msg": "文件超过 100MB 上限"}, 400)
                return
            fn = safe_name(fn)
            if not fn or not data:
                self._json({"ok": False, "msg": "无效的文件"}, 400)
                return
            req_path = (fields.get("path") or "").strip()
            dest_dir = safe_archive_dir(req_path)
            if req_path and not dest_dir:
                self._json({"ok": False, "msg": "目标路径无效 (必须在 /archive 内)"}, 400)
                return
            if not dest_dir:
                dest_dir = FILES_DIR
            os.makedirs(dest_dir, exist_ok=True)
            with open(os.path.join(dest_dir, fn), "wb") as f:
                f.write(data)
            self._json({"ok": True, "msg": f"已上传到 {dest_dir}/{fn} ({len(data)//1024} KB)"})
        elif path == "/api/skin/activate":
            body = self._read_json()
            if body == "TOOBIG":
                self._json({"ok": False, "msg": "请求体过大 (上限 1MB)"}, 413)
                return
            name = safe_name(body.get("name") if isinstance(body, dict) else None)
            if name and os.path.isfile(os.path.join(SKIN_DIR, name)):
                with open(os.path.join(SKIN_DIR, "active.json"), "w") as f:
                    json.dump({"skin": name}, f)
                self._json({"ok": True})
            else:
                self._json({"ok": False, "msg": "皮肤不存在"}, 404)
        elif path == "/api/audio/setlockchime":
            body = self._read_json()
            if body == "TOOBIG":
                self._json({"ok": False, "msg": "请求体过大 (上限 1MB)"}, 413)
                return
            name = safe_name(body.get("name") if isinstance(body, dict) else None)
            src = os.path.join(AUDIO_Q, name) if name else ""
            if name and os.path.isfile(src):
                with open(src, "rb") as f:
                    data = f.read()
                if not name.lower().endswith(".wav"):
                    self._json({"ok": False, "msg": "锁车音必须是 WAV (mp3 只能当喇叭音效)"})
                    return
                with open(os.path.join(AUDIO_Q, "LockChime.wav"), "wb") as f:
                    f.write(data)
                self._json({"ok": True})
            else:
                self._json({"ok": False, "msg": "文件不存在"}, 404)
        else:
            self._send(404, b"not found")

    def do_DELETE(self):
        if not self._gate():
            return
        path = urllib.parse.unquote(self.path)
        if not storage_ready() and path.startswith(("/api/skin/", "/api/audio/", "/api/usb", "/api/file")):
            self._json({"ok": False, "msg": "外接存储未挂载，当前仅可使用存储管理功能"}, 503)
            return
        if path.startswith("/api/skin/"):
            name = safe_name(path[len("/api/skin/"):])
            fp = os.path.join(SKIN_DIR, name) if name else ""
            if name and os.path.isfile(fp):
                os.remove(fp)
                if active_skin() == name:
                    os.remove(os.path.join(SKIN_DIR, "active.json"))
                self._json({"ok": True})
            else:
                self._json({"ok": False, "msg": "not found"}, 404)
        elif path.startswith("/api/audio/"):
            name = safe_name(path[len("/api/audio/"):].split("?")[0])
            done = "done=1" in self.path
            base = AUDIO_DONE if done else AUDIO_Q
            fp = os.path.join(base, name) if name else ""
            if name and os.path.isfile(fp) and name != "LockChime.wav":
                os.remove(fp)
                self._json({"ok": True})
            else:
                self._json({"ok": False, "msg": "not found"}, 404)
        elif path.startswith("/api/usb"):
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            fp = usb_real(q.get("path", [""])[0])
            if not fp or not os.path.isfile(fp) or fp == MNT:
                self._json({"ok": False, "msg": "not found"}, 404)
                return
            os.remove(fp)
            subprocess.run(["sync"], capture_output=True)
            self._json({"ok": True})
        elif path.startswith("/api/file"):
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            fp = safe_archive_path(q.get("path", [""])[0])
            if fp:
                os.remove(fp)
                self._json({"ok": True})
            else:
                self._json({"ok": False, "msg": "not found"}, 404)
        else:
            self._send(404, b"not found")


class BoundedServer(ThreadingHTTPServer):
    """限并发的线程式服务: 设备只有 1.4G 内存, 无限开线程会被慢连接拖垮。"""
    daemon_threads = True
    max_workers = 48
    # TCP accept 队列。socketserver 默认只有 5 —— 手机打开播放页会瞬间连上来
    # 4 路视频 + 封面 + 接口, 超过 5 的连接会被内核直接丢掉, 客户端要等 1s/2s/4s 重传,
    # 表现就是「有时秒开, 有时卡两三秒才出画面」。放宽到 128 让内核替我们排队。
    request_queue_size = 128

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._slots = threading.BoundedSemaphore(self.max_workers)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                request.close()
            except OSError:
                pass
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


if __name__ == "__main__":
    # OTA 自检: 只验证模块能完整加载 (常量/函数定义无误), 不启动服务、不碰硬件
    if "--ota-check" in sys.argv:
        print("ok %s" % APP_VERSION)
        sys.exit(0)
    if AUTH_CONF_ERR:
        print("FATAL: %s" % AUTH_CONF_ERR)
        print("为避免无认证暴露, 服务不启动。修复 %s 后重启 (或重跑 install.sh 重新生成密码)。" % AUTH_FILE)
        sys.exit(2)
    ensure_dirs()
    # 降低自身被 OOM 杀掉的概率 (合成任务会自己调高优先级先死)
    try:
        with open("/proc/self/oom_score_adj", "w") as f:
            f.write("-300")
    except OSError:
        pass
    # 先绑定端口: 若已有实例在跑, 重复实例会在这里直接退出,
    # 不会执行下面的"启动自愈"而误拆别人正在管理的挂载点
    try:
        srv = BoundedServer(("0.0.0.0", PORT), Handler)
    except OSError:
        print("port %d in use, another instance running? exit." % PORT)
        sys.exit(0)
    print(f"Sentry viewer on 0.0.0.0:{PORT}")
    print("auth: %s (%s)" % ("ON, user=" + AUTH_USER if AUTH_ON else "OFF - 公网可直接访问!", AUTH_FILE))
    # 清理上次进程中断遗留的导出临时包: /tmp 是 tmpfs, 大 zip 会吃内存并被换进 zram。
    # 端口已绑定成功 = 单实例, 此刻所有 exp_*.zip 都是孤儿, 直接删。
    try:
        _td = tempfile.gettempdir()
        _n = 0
        _sz = 0
        for _fn in os.listdir(_td):
            if _fn.startswith("exp_") and _fn.endswith(".zip"):
                _fp = os.path.join(_td, _fn)
                try:
                    _sz += os.path.getsize(_fp)
                    os.unlink(_fp)
                    _n += 1
                except OSError:
                    pass
        if _n:
            print("startup cleanup: removed %d orphan export zip(s), %.1f MB" % (_n, _sz / 1048576.0))
    except OSError:
        pass
    # 启动自愈: 若上次退出时镜像仍处于管理挂载状态, 恢复导出。
    # 短暂重试拿锁, 避免与正在进行的归档/同步互相拆台; 拿不到就完全不碰 U 盘。
    for _ in range(6):
        if _acquire_usb_flock():
            break
        time.sleep(0.4)
    if not storage_ready():
        print("startup self-heal skipped: external storage not mounted")
    elif _usb_flock_fd is not None:
        # 自愈失败不能让整个服务起不来: losetup/umount 缺失或被删时只告警
        try:
            if os.path.ismount(MNT):
                subprocess.run(["umount", MNT], capture_output=True)
            subprocess.run([LOSETUP, "-d", LOOPDEV], capture_output=True)
        except OSError as ex:
            print("startup self-heal skipped: %s" % ex)
        _gadget_rebind(True)
        _release_usb_flock()
    else:
        print("startup self-heal skipped: usb lock held by another process")
    threading.Thread(target=disk_guard, daemon=True).start()
    threading.Thread(target=health_logger, daemon=True).start()
    threading.Thread(target=notify_loop, daemon=True).start()
    threading.Thread(target=auto_update_loop, daemon=True).start()
    threading.Thread(target=prewarm_loop, daemon=True).start()
    threading.Thread(target=playback_sweep_loop, daemon=True).start()
    srv.serve_forever()
