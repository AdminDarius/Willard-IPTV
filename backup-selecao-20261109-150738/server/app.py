import os
import json
import sqlite3
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DB = DATA / "willard.db"
DATA.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin == "http://192.168.0.7:8080":
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Vary"] = "Origin"
    return response


def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db


def initialize():
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                playlist_type TEXT NOT NULL,
                server_url TEXT,
                username TEXT,
                password TEXT,
                source_url TEXT,
                file_path TEXT,
                is_default INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


@app.get("/")
def home():
    return render_template_string("""
    <!doctype html>
    <html lang="pt-br">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta charset="utf-8">
    <title>Willard IPTV - Gerenciador</title>
    <style>
    body{background:#11111b;color:#eee;font:16px Arial;max-width:700px;
    margin:30px auto;padding:16px}
    h1{color:#a78bfa}
    input,select,button{box-sizing:border-box;width:100%;padding:13px;
    margin:7px 0;border-radius:7px;border:1px solid #444;
    background:#222;color:white}
    button{background:#7545c5;border:0;font-weight:bold}
    .item{background:#222;padding:14px;margin:10px 0;border-radius:8px}
    .muted{color:#aaa;font-size:13px}
    </style>
    <h1>WILLARD IPTV</h1>
    <p class="muted">Gerenciador de playlists</p>
    <form id="form">
      <input name="name" placeholder="Nome da lista" required>
      <select name="type" id="type">
        <option value="xtream">Xtream Codes</option>
        <option value="m3u_url">M3U por URL</option>
      </select>
      <div id="xtream">
        <input name="server_url" placeholder="Endereço do servidor">
        <input name="username" placeholder="Usuário">
        <input name="password" placeholder="Senha" type="password">
      </div>
      <div id="m3u" hidden>
        <input name="source_url" placeholder="URL da playlist M3U">
      </div>
      <button type="submit">Adicionar playlist</button>
    </form>
    <h2>Minhas listas</h2>
    <div id="lists">Carregando...</div>
    <script>
    const headers = {"Content-Type":"application/json"};
    const type = document.getElementById("type");
    type.onchange = () => {
      document.getElementById("xtream").hidden = type.value !== "xtream";
      document.getElementById("m3u").hidden = type.value !== "m3u_url";
    };
    async function load(){
      const r=await fetch("/api/playlists",{headers});
      if(!r.ok){lists.textContent="Falha ao carregar playlists.";return}
      const data=await r.json();
      lists.innerHTML="";
      data.playlists.forEach(p=>{
        const div=document.createElement("div");
        div.className="item";
        const title=document.createElement("b");
        title.textContent=p.name;
        const info=document.createElement("p");
        info.className="muted";
        info.textContent=p.playlist_type+" · "+(p.is_default?"Padrão":"Salva");
        const del=document.createElement("button");
        del.textContent="Remover";
        del.onclick=async()=>{
          if(confirm("Remover esta playlist?")){
            await fetch("/api/playlists/"+p.id,{method:"DELETE",headers});
            load();
          }
        };
        const def=document.createElement("button");
        def.textContent="Definir como padrão";
        def.onclick=async()=>{
          await fetch("/api/playlists/"+p.id+"/default",{method:"PUT",headers});
          load();
        };
        div.append(title,info,def,del);
        lists.append(div);
      });
      if(!data.playlists.length) lists.textContent="Nenhuma playlist cadastrada.";
    }
    document.getElementById("form").onsubmit=async e=>{
      e.preventDefault();
      const f=new FormData(e.target);
      const payload=Object.fromEntries(f.entries());
      payload.playlist_type=payload.type;
      delete payload.type;
      const r=await fetch("/api/playlists",{method:"POST",headers,
        body:JSON.stringify(payload)});
      const result=await r.json();
      if(!r.ok){alert(result.error||"Erro");return}
      e.target.reset();load();
      alert("Playlist cadastrada!");
    };
    load();
    </script>
    </html>
    """)


@app.get("/api/health")
def health():
    return jsonify({"application": "Willard IPTV Server", "status": "online"})


@app.get("/api/playlists")
def get_playlists():
    with connect() as db:
        rows = db.execute("""
            SELECT id,name,playlist_type,server_url,username,
                   source_url,file_path,is_default,created_at,updated_at
            FROM playlists ORDER BY id
        """).fetchall()
    return jsonify({"playlists": [dict(r) for r in rows]})



def validate_m3u(source):
    from urllib.error import HTTPError, URLError
    from urllib.parse import urljoin, urlsplit
    from urllib.request import Request, HTTPRedirectHandler, build_opener

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        current = source
        redirects = 0
        opener = build_opener(NoRedirect())
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Connection": "close"
        }

        for attempt in range(3):
            try:
                for _ in range(6):
                    parsed = urlsplit(current)
                    if parsed.scheme not in ("http", "https") or not parsed.hostname:
                        return False, "Redirecionamento para endereço inválido."

                    req = Request(current, headers=headers, method="GET")
                    try:
                        response = opener.open(req, timeout=20)
                    except HTTPError as exc:
                        response = exc

                    with response:
                        status = response.code
                        if status in (301, 302, 303, 307, 308):
                            location = response.headers.get("Location")
                            if not location or redirects >= 5:
                                return False, "Limite de redirecionamentos excedido."
                            current = urljoin(current, location)
                            redirects += 1
                            continue

                        if status in (429,) or 500 <= status <= 599:
                            raise RuntimeError("HTTP_TEMPORARIO")

                        if status not in (200, 206):
                            return False, "O provedor respondeu HTTP " + str(status) + "."

                        body = response.read(65536)
                        normalized = body.lstrip(b"\xef\xbb\xbf \t\r\n")

                        if normalized.startswith(b"#EXTM3U"):
                            return True, "Playlist M3U acessível e confirmada."

                        if not normalized:
                            return False, "O servidor respondeu sem enviar conteúdo."

                        return False, "O endereço respondeu, mas não retornou o cabeçalho M3U."

                return False, "Limite de redirecionamentos excedido."

            except RuntimeError as exc:
                if str(exc) != "HTTP_TEMPORARIO":
                    return False, "Falha durante a validação da playlist."
            except (URLError, TimeoutError, OSError):
                if attempt == 2:
                    return False, "Não foi possível estabelecer conexão com o provedor."
            except Exception:
                return False, "Falha inesperada durante a validação da playlist."

            import time
            time.sleep(1 + attempt)

        return False, "Não foi possível validar a playlist após três tentativas."
    except Exception:
        return False, "Falha inesperada ao validar a playlist."


def validate_xtream(server, username, password):
    try:
        parsed = urllib.parse.urlsplit(server)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False, "Endereço do servidor Xtream inválido."

        endpoint = server.rstrip("/") + "/player_api.php"
        query = urllib.parse.urlencode({
            "username": username,
            "password": password
        })
        req = urllib.request.Request(
            endpoint + "?" + query,
            headers={"User-Agent": "Willard IPTV/1.0"}
        )

        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read(1024 * 1024 + 1)

        if len(raw) > 1024 * 1024:
            return False, "Resposta do servidor muito grande."

        data = json.loads(raw.decode("utf-8-sig"))
        info = data.get("user_info", {}) if isinstance(data, dict) else {}
        auth = info.get("auth")

        if str(auth) != "1" and auth is not True:
            return False, "Usuário ou senha recusados pelo servidor IPTV."

        status = str(info.get("status", "")).lower()
        if status and status not in ("active", "enabled"):
            return False, "A conta IPTV não está ativa."

        return True, "Acesso Xtream Codes validado."

    except Exception:
        return False, "Não foi possível validar o acesso Xtream Codes."


@app.post("/api/playlists")
def add_playlist():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    kind = data.get("playlist_type")

    if not name:
        return jsonify({"error": "Informe o nome da playlist"}), 400

    if kind == "xtream":
        server = str(data.get("server_url", "")).strip().rstrip("/")
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", "")).strip()
        if not all((server, username, password)):
            return jsonify({"error": "Preencha servidor, usuário e senha"}), 400
        values = (name, kind, server, username, password, None)
    elif kind == "m3u_url":
        source = str(data.get("source_url", "")).strip()
        if not source.startswith(("http://", "https://")):
            return jsonify({"error": "URL M3U inválida"}), 400
        values = (name, kind, None, None, None, source)
    else:
        return jsonify({"error": "Tipo de playlist inválido"}), 400

    with connect() as db:
        cur = db.execute("""
            INSERT INTO playlists
            (name,playlist_type,server_url,username,password,source_url)
            VALUES (?,?,?,?,?,?)
        """, values)
        playlist_id = cur.lastrowid

    return jsonify({"success": True, "id": playlist_id}), 201


@app.delete("/api/playlists/<int:playlist_id>")
def delete_playlist(playlist_id):
    with connect() as db:
        cur = db.execute("DELETE FROM playlists WHERE id=?", (playlist_id,))
    if not cur.rowcount:
        return jsonify({"error": "Playlist não encontrada"}), 404
    return jsonify({"success": True})


@app.put("/api/playlists/<int:playlist_id>/default")
def set_default(playlist_id):
    with connect() as db:
        exists = db.execute(
            "SELECT id FROM playlists WHERE id=?", (playlist_id,)
        ).fetchone()
        if not exists:
            return jsonify({"error": "Playlist não encontrada"}), 404
        db.execute("UPDATE playlists SET is_default=0")
        db.execute(
            "UPDATE playlists SET is_default=1 WHERE id=?", (playlist_id,)
        )
    return jsonify({"success": True})


initialize()

if __name__ == "__main__":
    print("\\n===== WILLARD IPTV SERVER =====")
    print("Painel: http://0.0.0.0:8767")
    print("Autenticação: desativada.")
    app.run(host="0.0.0.0", port=8767, debug=False)
