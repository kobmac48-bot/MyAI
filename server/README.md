# MyAI Ollama server

This small Python standard-library service exposes only Ollama's model-list and
chat endpoints. Keep the service bound to localhost and put Caddy (or another
HTTPS reverse proxy) in front of it. Do not expose Ollama's port `11434` or the
proxy's port `8765` directly to the internet.

## Requirements

- A Linux VPS supported by Ollama
- A DNS name pointing to the VPS
- Ollama installed and running on the VPS
- Python 3.8 or newer
- Caddy or another reverse proxy that provides valid HTTPS

Install Ollama and download a model on the VPS, for example:

```sh
ollama pull llama3.1
```

The model needs several gigabytes of storage and suitable memory/compute on the
VPS. The 32-bit Windows client does not download or run models locally.

## Configure

Copy this repository to `/opt/myai` and install the systemd unit:

```sh
sudo useradd --system --home /var/lib/myai --shell /usr/sbin/nologin myai
sudo install -o root -g myai -m 0640 server/myai-server.service /etc/systemd/system/myai-server.service
```

Create a long random bearer token and a protected environment file:

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
sudo install -o root -g myai -m 0640 /dev/null /etc/myai-server.env
sudoedit /etc/myai-server.env
```

Put the generated value in `/etc/myai-server.env`:

```text
MYAI_SERVER_TOKEN=replace-with-the-generated-random-value
```

Configure Caddy with the example in `Caddyfile.example`, replacing
`myai.example.com` with your real DNS name. Caddy obtains and renews the HTTPS
certificate automatically. Restrict the VPS firewall to SSH from trusted
addresses and public HTTPS (TCP 443). Do not open TCP 11434 or 8765.

Start both services:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now myai-server
sudo systemctl status myai-server
```

Check the proxy locally before configuring clients:

```sh
curl --fail-with-body \
  -H "Authorization: Bearer $(sudo sed -n 's/^MYAI_SERVER_TOKEN=//p' /etc/myai-server.env)" \
  http://127.0.0.1:8765/api/tags
```

The same bearer token is required for all requests. Keep it private, rotate it
if a client is lost, and give a separate token to each trusted user by running
separate server instances if individual revocation is required. Requests are
not logged by the proxy. Chat prompts and model responses are processed by the
VPS and sent to its local Ollama service.

## Windows 7/8 x86 client

Download `MyAI-windows-x86.exe` from the GitHub release, run it, and enter the
public HTTPS address and bearer token under **Server einstellen**. The address
must begin with `https://`. The client stores the token in
`%APPDATA%\MyAI\remote-server.json` without encryption; protect the Windows
account and do not share that file.

This lightweight client requires no Ollama installation and has no local model
training. It is intended for 32-bit Windows 7/8. Windows XP and Vista are not
supported because they cannot reliably establish modern, certificate-verified
HTTPS connections to a public server.
