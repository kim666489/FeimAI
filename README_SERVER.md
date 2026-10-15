# FeimAI Server: ติดตั้ง เริ่มใช้งาน และเชื่อมต่อ

เอกสารนี้อธิบายการเปิด FeimAI API Server และเชื่อมต่อทั้งจากแอป FeimAI
และโปรแกรมที่รองรับ OpenAI-compatible API

## ภาพรวม

`server.py` เปิด HTTP API รูปแบบ OpenAI-compatible โดยส่งคำขอแชตไปยัง Ollama
ที่ตั้งไว้ใน `config/config.json` (`local.host`) ส่วนการสร้างภาพใช้ image
provider ใน config เดียวกัน

API ที่มีให้:

| Method | Endpoint | ใช้ทำอะไร |
|---|---|---|
| `GET` | `/health` | ตรวจว่า API server ทำงานอยู่ |
| `GET` | `/v1/models` | ดูรายชื่อโมเดลที่ Ollama ใช้งานได้ |
| `POST` | `/v1/chat/completions` | แชต, streaming (SSE), tool calls และรับภาพแบบ base64 data URL |
| `POST` | `/v1/images/generations` | สร้างภาพจาก image provider ที่ตั้งค่าไว้ |

## สิ่งที่ต้องมี

1. Windows และ Python environment ที่ใช้กับ FeimAI
2. ติดตั้งและเปิด Ollama ให้ทำงานที่ host ซึ่งระบุใน `config/config.json`
3. ดาวน์โหลดโมเดล Ollama อย่างน้อยหนึ่งโมเดล ตัวอย่าง:

   ```powershell
   ollama pull qwen2.5:7b
   ```

4. ใช้ Command Prompt หรือ PowerShell ที่เปิดอยู่ในโฟลเดอร์โปรเจกต์

## เริ่ม Server บนเครื่องเดียวกัน

เปิด Ollama ก่อน จากนั้นเปิด PowerShell ในโฟลเดอร์ FeimAI แล้วสั่ง:

```powershell
.\env\Scripts\python.exe .\server.py
```

ค่าเริ่มต้น:

- Listen address: `127.0.0.1`
- Port: `8000`
- Ollama host: ค่าจาก `local.host` ใน `config/config.json`
- API key: ไม่บังคับเมื่อฟังเฉพาะ loopback

ทดสอบว่า server ทำงาน:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

ผลที่คาดหวัง:

```json
{
  "status": "ok",
  "backend": "ollama"
}
```

ตรวจสอบรายชื่อโมเดล:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/v1/models
```

หยุด server ด้วย `Ctrl+C`

## เชื่อมต่อจากแอป FeimAI

1. เปิด `server.py` ค้างไว้
2. เปิดแอป FeimAI แล้วกด **Settings**
3. ในแท็บ **General** ตั้ง **Server URL** เป็น URL ของ FeimAI API เช่น:
   `http://127.0.0.1:8000`
4. ในแท็บ **API** ตั้งค่า:
   - **Base URL**: เว้นว่างเพื่อใช้ Server URL จาก General หรือใส่
     `http://127.0.0.1:8000`
   - **Endpoint path**: `/v1/chat/completions`
   - **API key**: เว้นว่างเมื่อใช้บนเครื่องเดียวโดยไม่ตั้ง key
   - **Fallback model**: เลือกได้เมื่อโหลดรายชื่อโมเดลไม่ได้
5. กด **Save**
6. เลือก backend เป็น `api` จากแถบบน และเลือกโมเดลจากรายการ

รายชื่อโมเดลในรายการมาจาก endpoint `/v1/models` ของ server หากไม่มีรายการ
ให้ตรวจว่า Ollama ทำงานอยู่และมีโมเดลที่ดาวน์โหลดไว้แล้ว

## เชื่อมต่อจากเครื่องอื่นในเครือข่าย

> **ความปลอดภัย:** อย่าเปิดรับการเชื่อมต่อจากเครือข่ายโดยไม่มี API key
> server จะปฏิเสธการ bind ไปยัง network interface หากไม่ได้ตั้ง key

ตั้งค่าตัวแปรใน PowerShell ก่อนเริ่ม server:

```powershell
$env:FEIMAI_HOST = "0.0.0.0"
$env:FEIMAI_PORT = "8000"
$env:FEIMAI_API_KEY = "ใส่คีย์สุ่มที่ยาวและคาดเดายาก"
.\env\Scripts\python.exe .\server.py
```

ดู IP ภายในเครือข่ายของเครื่องที่รัน server:

```powershell
ipconfig
```

จากเครื่อง client ให้ตั้ง FeimAI **Server URL** หรือ **API Base URL** เป็น
`http://<IP-ของเครื่อง-server>:8000` และใส่ key เดียวกับ `FEIMAI_API_KEY`
ในช่อง **API key** ของ FeimAI Settings

ถ้าเชื่อมต่อไม่ได้ ให้ตรวจ Windows Firewall ว่าอนุญาต TCP port ที่เลือก
สำหรับเครือข่ายส่วนตัวแล้วหรือยัง ใช้เฉพาะ LAN ที่เชื่อถือได้: API server
นี้ให้บริการ HTTP โดยตรงและไม่ได้ตั้งค่า TLS/HTTPS ให้เอง

ตัวแปรที่ server รองรับ:

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `FEIMAI_HOST` | `127.0.0.1` | IP/interface ที่ server ใช้รับการเชื่อมต่อ |
| `FEIMAI_PORT` | `8000` | TCP port |
| `FEIMAI_API_KEY` | ว่าง | key ที่ client ต้องส่งเป็น Bearer token หรือ `X-API-Key` |

ตัวแปรเหล่านี้มีผลกับการเปิด server ไม่ได้แก้ค่า `local.host` ของ Ollama
การเปลี่ยน Ollama host ให้แก้ `local.host` ใน `config/config.json`

## เรียก API ด้วย PowerShell

ดึงรายชื่อโมเดล:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/v1/models" `
  -Headers @{ Authorization = "Bearer ใส่คีย์ถ้าตั้งไว้" }
```

ส่งข้อความหาโมเดล (เปลี่ยน `qwen2.5:7b` ให้เป็น ID ที่ได้จาก `/v1/models`):

```powershell
$headers = @{
  "Content-Type" = "application/json"
  "Authorization" = "Bearer ใส่คีย์ถ้าตั้งไว้"
}
$body = @{
  model = "qwen2.5:7b"
  messages = @(
    @{ role = "user"; content = "สวัสดี ช่วยแนะนำตัวหน่อย" }
  )
} | ConvertTo-Json -Depth 10

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/v1/chat/completions" `
  -Method Post `
  -Headers $headers `
  -Body $body
```

เมื่อไม่ได้ตั้ง API key สามารถเอา header `Authorization` ออกได้

## เรียก API ด้วย Python

ตัวอย่างนี้ใช้ไลบรารีมาตรฐาน ไม่ต้องติดตั้งแพ็กเกจเพิ่ม:

```python
import json
from urllib.request import Request, urlopen

url = "http://127.0.0.1:8000/v1/chat/completions"
payload = {
    "model": "qwen2.5:7b",
    "messages": [{"role": "user", "content": "สวัสดี"}],
}
headers = {"Content-Type": "application/json"}
api_key = ""  # ใส่ค่า FEIMAI_API_KEY ถ้า server เปิดใช้ key
if api_key:
    headers["Authorization"] = f"Bearer {api_key}"

request = Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers=headers,
    method="POST",
)
with urlopen(request, timeout=120) as response:
    result = json.loads(response.read().decode("utf-8"))
print(result["choices"][0]["message"]["content"])
```

## Streaming

ตั้ง `"stream": true` ใน request ไปที่ `/v1/chat/completions` server จะส่ง
คำตอบเป็น Server-Sent Events (SSE) ทีละ chunk และปิดท้ายด้วย `data: [DONE]`
ตัวอย่าง:

```json
{
  "model": "qwen2.5:7b",
  "messages": [{"role": "user", "content": "เล่าเรื่องสั้น"}],
  "stream": true
}
```

FeimAI keeps one Ollama client open to reuse its HTTP connection pool. It also
coalesces small text chunks before writing SSE events, reducing per-token
flush overhead while bounding the extra wait. These options are read from
`config/config.json` when the server starts:

| Setting | Default | Purpose |
|---|---:|---|
| `server.ollama_keep_alive` | `10m` | Keep the model loaded in Ollama after a request. Use an empty value for Ollama's default. |
| `server.stream_flush_interval_ms` | `20` | Maximum time to buffer a partial text event before flushing. |
| `server.stream_flush_chars` | `256` | Flush when buffered text reaches this many characters. |

Edit the `server` object in the `config/config.json` used by the API server,
then restart the server. The FeimAI Settings controls write to the local
client's config; they affect a server only when it reads the same config file.
For a Colab-hosted server, update the config copy on Colab.

## ส่งภาพให้โมเดลที่รองรับ vision

ส่งภาพเป็น base64 data URL ใน `messages[].content` ตามรูปแบบ OpenAI-compatible
และใช้โมเดล vision ที่ Ollama รองรับ:

```json
{
  "model": "โมเดล-vision-ของคุณ",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "ช่วยอธิบายภาพนี้"},
      {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,<BASE64_IMAGE_DATA>"}
      }
    ]
  }]
}
```

server รับเฉพาะภาพแบบ base64 data URL ไม่ดาวน์โหลดภาพจาก URL ภายนอก

## สร้างภาพ

`POST /v1/images/generations` ใช้ image provider ที่ตั้งไว้ใน `image` ของ
`config/config.json` เช่น Automatic1111/Forge หรือ OpenAI-compatible image API
ตัวอย่าง request:

```json
{
  "prompt": "a small house in a forest, watercolor",
  "size": "512x512",
  "response_format": "b64_json"
}
```

`response_format` รองรับเฉพาะ `b64_json`; คำตอบอยู่ใน `data[0].b64_json`
ไฟล์ภาพต้นฉบับจะถูกบันทึกตามการตั้งค่า image provider ของ FeimAI

## Tool calls

แชต API รองรับ OpenAI-style `tools` และส่งผลการเรียก tool กลับในคำตอบ
**server จะไม่รัน file, shell หรือ web tools แทน client** ในแอป FeimAI
การจัดการ tool และการถามยืนยันยังเกิดที่ FeimAI client ตามการตั้งค่าใน
Settings ผู้ใช้ API client อื่นต้องจัดการ tool calls/ผลลัพธ์ต่อเอง

FeimAI also supports local Python tool modules. Put `.py` files directly in
the configured `Module` folder (default `./Module`) and enable the module in
**Settings > Tools**. A module exports a `TOOLS` list containing OpenAI-style
tool descriptions (`name`, `description`, and object `parameters`) and a
`run(tool_name, arguments, context)` function. Its public tool name is prefixed
with the module filename, e.g. `current_time__get_current_time`. `context`
provides the workspace and module-folder paths. Modules are disabled by
default and run locally in the FeimAI client with the user's full permissions;
they are not sandboxed. Only enable code you trust.

The chat sidebar supports deleting one saved conversation or clearing all
history, with confirmation. **Settings > Memory & History** also provides
direct editing and confirmed deletion of the configured Markdown user-memory
file, in addition to chat summarization.

## FeimRemote: access the Host from another device

FeimRemote serves an authenticated chat page at `/remote` on the same FeimAI
API port. It reuses the server's existing Ollama client and loaded model; it
does not start a second model process. Typed requests and optional browser
speech recognition both go to that Host. Speech recognition is provided by
the browser's Web Speech API, so browser support and language availability
vary.

1. On the Host, open FeimAI **Settings > FeimRemote**.
2. Add an account with a username and a password of at least 12 characters.
   Passwords are stored as salted PBKDF2 hashes in `config/feimremote.json`.
3. Set per-operation Host tool permissions. All accounts share these Host
   permissions. Shell is off by default and grants powerful access if enabled.
4. Enable FeimRemote, save Settings, and restart `server.py`.
5. Keep FeimAI bound to loopback and expose it through a trusted HTTPS tunnel
   (or another HTTPS reverse proxy). Do not expose this HTTP server directly to
   the internet. Open `https://<your-tunnel>/remote` on the client device.

Each successful sign-in receives a random, expiring bearer token. Login is
rate-limited, tokens are held in memory and invalidated when the server
restarts, and chat history is stored separately per username in
`data/feimremote_history.json`. The web page stores its token in tab-scoped
session storage and offers sign-out and per-account history clearing.

For the interactive CLI client, run on a machine with this project installed:

```powershell
.\feimremote.bat --url https://<your-tunnel>
```

Or send one prompt and exit:

```powershell
.\feimremote.bat --url https://<your-tunnel> --username <account> --message "สวัสดี"
```

The CLI prompts for the password; do not pass credentials as command-line
arguments. Use `python -m FeimRemote.cli` with `PYTHONPATH=src` on systems
without the batch launcher.

`config/feimremote.json` is independent from the FeimAI config. Settings in
the desktop application update the local copy only. For a server hosted on
Colab, transfer the FeimRemote config (which contains password hashes and
permissions) to the Colab project securely, then restart the server there.
Keep that file private. The server itself does not provide TLS; HTTPS must be
terminated by the tunnel/proxy. FeimRemote is disabled by default.

## การตั้งค่าและไฟล์

- `config/config.json` คือ config หลักที่แอปเปิดผ่าน `src/app.py` และ server
  ใช้อ่านค่า `local.host` กับ image provider
- `config.json` ที่ root เป็น config อีกชุดหนึ่ง; server ใช้เป็น fallback
  เฉพาะเมื่อไม่มี `config/config.json`
- การเปลี่ยน config ขณะ server ทำงานจะไม่มีผลจนกว่าจะหยุดและเริ่ม server ใหม่
- API key ของ FeimAI server ตั้งผ่าน `FEIMAI_API_KEY` ใน environment ไม่ได้อ่าน
  จาก `api.key` ใน config (ค่านั้นใช้เป็น key ฝั่ง client สำหรับเรียก upstream)

## แก้ปัญหาเบื้องต้น

| อาการ | ตรวจสอบ |
|---|---|
| `/health` เข้าไม่ได้ | ตรวจว่า `server.py` ยังทำงานและใช้ host/port ที่ถูกต้อง |
| `/v1/models` ตอบ error | เปิด Ollama และตรวจ `local.host` ใน `config/config.json` |
| ไม่มีโมเดลให้เลือก | ดาวน์โหลดโมเดลด้วย `ollama pull <model>` แล้ว reload รายการใน FeimAI |
| ได้ `401 Unauthorized` | ตรวจว่า client ส่ง Bearer token หรือ `X-API-Key` ตรงกับ `FEIMAI_API_KEY` |
| เชื่อมจากเครื่องอื่นไม่ได้ | ใช้ `FEIMAI_HOST=0.0.0.0`, ตรวจ IP/port และ Windows Firewall |
| สร้างภาพไม่ได้ | ตรวจว่า image provider ที่ตั้งค่าไว้ทำงานและ `image.baseURL` ถูกต้อง |
| ตอบช้าหรือ timeout | ตรวจขนาดโมเดล ทรัพยากรเครื่อง และ timeout ของ client |
