import os
import re
import sys
from sys import argv
import threading
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
import mimetypes

import requests
import traceback                        # エラー詳細情報取得に使用
import ctypes.wintypes                  # 普段使用しているデスクトップにフォーカスを変更させるために使用
from datetime import datetime           # 作成フォルダなどに日付を記載するのに使用
import tkinter as tk
from tkinter import ttk, messagebox

#=============================================================================================
# グローバル関数
#=============================================================================================
APP_TITLE = "Web File Gulpin"
DEFAULT_URL = "https://pokemondb.net/pokedex/national"
RESOURCE_DIR_CANDIDATES = ["resources", "resource", "assets", "img", "_internal"]
EXE_ICON_FILE = "exe_icon.ico"
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg",
    ".ico", ".tif", ".tiff", ".avif", ".jfif", ".avif"
}
OTHER_EXTENSIONS = {
    ".css", ".js", ".mjs", ".cjs",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".pdf", ".zip", ".rar", ".7z",
    ".mp3", ".wav", ".mp4", ".webm",
    ".xml", ".txt", ".map"
}

#ffmpegの場所が判らずにエラーを起こすので即席パスを作製して場所を読めるようにする
dir_name = os.path.dirname(os.path.abspath(argv[0]))        # exe化した際は実行している方のファイルのディレクトリ
cwd = os.path.dirname(__file__)                             # exe化した際は一時ファイルの方のpyファイルのディレクトリ
icon_path = os.path.join(cwd,'exe_logo.ico')                # アイコン画像の読み込みと設定

os.environ['PATH'] = '{};{}'.format(cwd, os.environ['PATH'])#セミコロン付きでPATHの先頭に追加

#=============================================================================================
# メイン処理
#=============================================================================================
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("680x500")

        self.url_var = tk.StringVar(value=DEFAULT_URL)
        self.get_links_var = tk.BooleanVar(value=False)
        self.get_json_var = tk.BooleanVar(value=True)
        self.get_image_var = tk.BooleanVar(value=False)
        self.get_other_var = tk.BooleanVar(value=False)
        self.get_all_var = tk.BooleanVar(value=False)

        # ブラウザっぽいヘッダーをつける
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Referer": self.url_var.get().strip() or DEFAULT_URL,
        })

        self._build_ui()
    
    # -------------------------------
    # get data category
    # -------------------------------
    def get_file_category(self, link: str, source_kind: str = "href") -> str | None:
        parsed = urlparse(link)
        path = parsed.path.lower()
        query = parsed.query.lower()

        _, ext = os.path.splitext(path)

        # 0) CSS / JS / フォント / その他の固定拡張子
        if ext in OTHER_EXTENSIONS:
            if self.get_all_var.get() or self.get_other_var.get():
                return "others"
            return None

        # 1) JSON
        if ext == ".json":
            if self.get_all_var.get() or self.get_json_var.get():
                return "json"
            return None

        # 2) 画像っぽいもの
        if source_kind in {"img", "lazy-img", "srcset", "bg-image", "poster"}:
            if self.get_all_var.get() or self.get_image_var.get():
                return "images"
            return None

        if ext in IMAGE_EXTENSIONS:
            if self.get_all_var.get() or self.get_image_var.get():
                return "images"
            return None

        if any(x in query for x in ["format=avif", "fm=avif", "format=webp", "fm=webp"]):
            if self.get_all_var.get() or self.get_image_var.get():
                return "images"
            return None

        # 3) href の普通のリンク
        # 拡張子なし or .html / .htm / .php / .asp / .aspx / .jsp のみ links 扱い
        if source_kind == "href":
            html_like_exts = {"", ".html", ".htm", ".php", ".asp", ".aspx", ".jsp"}
            if ext in html_like_exts:
                if self.get_all_var.get() or self.get_links_var.get():
                    return "links"
            return None

        # 4) その他ファイル
        if self.get_all_var.get() or self.get_other_var.get():
            return "others"

        return None

    # -------------------------------
    # Main Execution
    # -------------------------------
    def start_run(self):
        thread = threading.Thread(target=self.run_download, daemon=True)
        thread.start()

    def run_download(self):
        try:
            url = self.url_var.get().strip()

            if not url:
                error_message_activate(None, "入力エラー", "対象URLを入力してください。")
                return

            out_dir = Path(get_output_path(self.output_combo.get()))
            self.log_append(f"[OK] 取得中: output path: {out_dir}")
            out_dir.mkdir(parents=True, exist_ok=True)

            self.log_append(f"[INFO] 開始: {url}")

            html = self.fetch_html(url)
            if not html:
                self.log_append("[WARN] ページ取得に失敗したため、リンク抽出をスキップします。", "WARN")
                self.log_append("[OK] 処理終了", "OK")
                return

            links = self.extract_links(url, html)
            self.log_append(f"[OK] リンク抽出: {len(links)} 件", "OK")

            if self.get_links_var.get():
                self.save_link_list(links, out_dir)

            targets = self.filter_targets(links)

            if not targets:
                self.log_append("[WARN] ダウンロード対象がありません。", "WARN")
                self.log_append("[OK] 処理終了", "OK")
                return

            success_count = 0
            fail_count = 0

            for link, category in targets:
                ok = self.download_file(link, out_dir, category)
                if ok:
                    success_count += 1
                else:
                    fail_count += 1
            
            self.log_append("")
            self.log_append(f"====================================================================", "INFO")
            self.log_append(f"[SUMMARY] 成功: {success_count} 件 / 失敗: {fail_count} 件", "OK")
            self.log_append("[OK] 処理完了", "OK")

        except Exception as e:
            self.log_append(f"[ERROR] {e}", "ERROR")
            error_message_activate(e, "実行エラー", "ダウンロード処理でエラーが発生しました")

    def fetch_html(self, url: str) -> str | None:
        try:
            self.session.headers["Referer"] = url
            res = self.session.get(url, timeout=30)
            res.raise_for_status()
            return res.text
        except requests.RequestException as e:
            self.log_append(f"[ERROR] ページ取得失敗: {url} -> {e}", "ERROR")
            return None

    def extract_links(self, base_url: str, html: str) -> list[tuple[str, str]]:
        # HTMLから各種URLを抽出する 戻り値: [(absolute_url, source_kind), ...]
        # source_kind 例: href, img, lazy-img, srcset, bg-image
        results = []
        seen = set()

        def add_url(raw_url: str, kind: str):
            if not raw_url:
                return
            raw_url = raw_url.strip()
            if not raw_url:
                return
            if raw_url.startswith("data:"):
                return

            abs_url = urljoin(base_url, raw_url)
            key = (abs_url, kind)
            if key not in seen:
                seen.add(key)
                results.append((abs_url, kind))

        # href
        for m in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
            add_url(m, "href")

        # src
        for m in re.findall(r'src=["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
            add_url(m, "img")

        # data-src / lazy系
        for attr in ["data-src", "data-lazy-src", "data-original", "data-thumb", "data-image"]:
            pattern = rf'{attr}=["\']([^"\']+)["\']'
            for m in re.findall(pattern, html, flags=re.IGNORECASE):
                add_url(m, "lazy-img")

        # poster
        for m in re.findall(r'poster=["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
            add_url(m, "poster")

        # srcset
        for srcset in re.findall(r'srcset=["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
            parts = [x.strip() for x in srcset.split(",")]
            for part in parts:
                url_only = part.split()[0].strip()
                add_url(url_only, "srcset")

        # background-image:url(...)
        for m in re.findall(r'background-image\s*:\s*url\(([^)]+)\)', html, flags=re.IGNORECASE):
            add_url(m.strip("\"' "), "bg-image")

        return results

    def filter_targets(self, links: list[tuple[str, str]]) -> list[tuple[str, str]]:
        result = []

        for link, source_kind in links:
            category = self.get_file_category(link, source_kind)
            if category:
                result.append((link, category))

        return result

    # -------------------------------
    # リンク一覧作成関連
    # -------------------------------
    def save_link_list(self, links: list[tuple[str, str]], out_dir: Path):
        link_dir = out_dir / "links"
        link_dir.mkdir(parents=True, exist_ok=True)

        txt_path = link_dir / "links.txt"

        # kind と url を一緒に保存
        lines = [f"{kind}\t{url}" for url, kind in links]

        txt_path.write_text("\n".join(lines), encoding="utf-8")
        self.log_append(f"[OK] リンク一覧保存: {txt_path}", "OK")

        # 閲覧しやすいHTML版も保存
        self.save_link_html(links, out_dir)

    def save_link_html(self, links: list[tuple[str, str]], out_dir: Path):
        link_dir = out_dir / "links"
        link_dir.mkdir(parents=True, exist_ok=True)

        html_path = link_dir / "links.html"

        rows = []
        for url, kind in links:
            safe_url = (
                url.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;")
            )
            safe_kind = (
                kind.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;")
            )

            rows.append(f"""
            <tr>
                <td>{safe_kind}</td>
                <td><a href="{safe_url}" target="_blank" rel="noopener noreferrer">{safe_url}</a></td>
            </tr>
            """)

        html = f"""<!DOCTYPE html>
            <html lang="ja">
            <head>
                <meta charset="UTF-8">
                <title>Link List</title>
                <style>
                    body {{
                        font-family: "Yu Gothic UI", "Meiryo", sans-serif;
                        background: #f7f7f7;
                        color: #222;
                        margin: 20px;
                    }}
                    h1 {{
                        margin-bottom: 10px;
                    }}
                    .summary {{
                        margin-bottom: 16px;
                        color: #555;
                    }}
                    table {{
                        width: 100%;
                        border-collapse: collapse;
                        background: #fff;
                    }}
                    th, td {{
                        border: 1px solid #ccc;
                        padding: 8px 10px;
                        text-align: left;
                        vertical-align: top;
                    }}
                    th {{
                        background: #e9eef5;
                    }}
                    tr:nth-child(even) {{
                        background: #f9fbfd;
                    }}
                    a {{
                        color: #0066cc;
                        text-decoration: none;
                        word-break: break-all;
                    }}
                    a:hover {{
                        text-decoration: underline;
                    }}
                </style>
            </head>
            <body>
                <h1>取得リンク一覧</h1>
                <div class="summary">件数: {len(links)} 件</div>

                <table>
                    <thead>
                        <tr>
                            <th style="width: 140px;">種別</th>
                            <th>URL</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(rows)}
                    </tbody>
                </table>
            </body>
            </html>
            """
        html_path.write_text(html, encoding="utf-8")
        self.log_append(f"[OK] リンクHTML保存: {html_path}", "OK")

    def guess_extension_from_content_type(self, content_type: str) -> str:
        content_type = (content_type or "").split(";")[0].strip().lower()
        mapping = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/svg+xml": ".svg",
            "image/x-icon": ".ico",
            "image/tiff": ".tif",
            "image/avif": ".avif",
            "application/json": ".json",
            "text/plain": ".txt",
            "text/html": ".html",
        }
        return mapping.get(content_type, mimetypes.guess_extension(content_type) or "")

    def safe_filename_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        name = os.path.basename(parsed.path.rstrip("/"))
        name = unquote(name).strip()

        if not name:
            name = "downloaded_file"

        for ch in ['<', '>', ':', '"', '/', '\\', '|', '?', '*', '#']:
            name = name.replace(ch, "_")

        return name

    def download_file(self, url: str, out_dir: Path, category: str) -> bool:
        try:
            self.session.headers["Referer"] = url
            res = self.session.get(url, timeout=60)
            res.raise_for_status()

            content_type = (res.headers.get("Content-Type", "") or "").lower()
            ext_from_type = self.guess_extension_from_content_type(content_type)

            # Content-Typeでカテゴリ補正（ただしチェック状態の方が優先）
            if content_type.startswith("image/"):
                if self.get_all_var.get() or self.get_image_var.get():
                    category = "images"
                else:
                    return False

            elif "json" in content_type:
                if self.get_all_var.get() or self.get_json_var.get():
                    category = "json"
                else:
                    return False

            elif "text/html" in content_type:
                if self.get_all_var.get() or self.get_links_var.get():
                    category = "links"
                else:
                    return False

            elif (
                "text/css" in content_type
                or "javascript" in content_type
                or "ecmascript" in content_type
                or "font/" in content_type
                or "application/font" in content_type
                or "application/octet-stream" in content_type
            ):
                if self.get_all_var.get() or self.get_other_var.get():
                    category = "others"
                else:
                    return False

            category_dir = out_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)

            filename = self.safe_filename_from_url(url)

            base, ext = os.path.splitext(filename)
            if not ext and ext_from_type:
                filename = base + ext_from_type

            # links に入る html は拡張子が無ければ .html を付ける
            if category == "links":
                base, ext = os.path.splitext(filename)
                if not ext:
                    filename = base + ".html"

            dst = category_dir / filename

            self.log_append(f"[INFO] 取得中 [{category}]: {filename}")
            dst.write_bytes(res.content)
            self.log_append(f"[OK] 保存: {dst}", "OK")
            return True

        except requests.RequestException as e:
            self.log_append(f"[ERROR] 保存失敗: {url} -> {e}", "ERROR")
            return False

        except Exception as e:
            self.log_append(f"[ERROR] 保存中に予期しないエラー: {url} -> {e}", "ERROR")
            return False
    
    # -------------------------------
    # 画面UI構成
    # -------------------------------
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        self.root.iconbitmap(default=icon_path)

        # URL
        row1 = ttk.Frame(main)
        row1.pack(fill="x", pady=(0, 8))

        ttk.Label(row1, text="対象URL", width=12).pack(side="left")
        ttk.Entry(row1, textvariable=self.url_var).pack(side="left", fill="x", expand=True, padx=(0, 8))

        # 保存先
        row2 = ttk.Frame(main)
        row2.pack(fill="x", pady=(0, 8))
        ttk.Label(row2, text="保存先", width=12).pack(side="left")

        # プルダウンメニューの値
        options = ["デスクトップ", "このアプリと同じ場所"]

        # プルダウンメニューの作成
        self.output_combo = ttk.Combobox(row2, values=options, state="readonly", width=30)
        self.output_combo.set("デスクトップ")
        self.output_combo.pack(side="left", padx=(0, 8))
        
        # チェック
        target_frame = ttk.LabelFrame(main, text="取得対象")
        target_frame.pack(fill="x", pady=(0, 8))

        check_row = ttk.Frame(target_frame)
        check_row.pack(fill="x", padx=8, pady=4)

        ttk.Checkbutton(check_row, text="リンク一覧のみ取得", variable=self.get_links_var).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(check_row, text="JSONファイルを取得", variable=self.get_json_var).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(check_row, text="画像を取得", variable=self.get_image_var).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(check_row, text="その他ファイルを取得", variable=self.get_other_var).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(check_row, text="すべて取得", variable=self.get_all_var, command=self.on_toggle_all).pack(side="left")

        # ボタン
        row3 = ttk.Frame(main)
        row3.pack(fill="x", pady=(0, 8))

        ttk.Button(row3, text="実行", command=self.start_run).pack(side="left")
        ttk.Button(row3, text="ログクリア", command=self.clear_log).pack(side="left", padx=(8, 0))

        # ログ
        log_frame = ttk.LabelFrame(main, text="実行ログ")
        log_frame.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            log_frame,
            bg="#111111",
            fg="#f0f0f0",
            insertbackground="#ffffff",
            wrap="word"
        )
        self.log_text.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.log_text.tag_config("INFO", foreground="#dddddd")
        self.log_text.tag_config("OK", foreground="#66dd66")
        self.log_text.tag_config("WARN", foreground="#ffcc66")
        self.log_text.tag_config("ERROR", foreground="#ff6666")

        self.log_append(" __    __     _        __ _ _                    _       _       ")
        self.log_append("/ / /\ \ \___| |__    / _(_) | ___    __ _ _   _| |_ __ (_)_ __ ")
        self.log_append("\ \/  \/ / _ \ '_ \  | |_| | |/ _ \  / _` | | | | | '_ \| | '_ \ ")
        self.log_append(" \  /\  /  __/ |_) | |  _| | |  __/ | (_| | |_| | | |_) | | | | |")
        self.log_append("  \/  \/ \___|_.__/  |_| |_|_|\___|  \__, |\__,_|_| .__/|_|_| |_|")
        self.log_append("                                     |___/        |_|            ")
        self.log_append("")
        self.log_append("Created by               : Sad (Twitter : @Tower_16_C2H4)")
        self.log_append("Version                  : 1.1f")
        self.log_append("Development environment  : Python3.10.8 ")
        self.log_append("Operating environment    : Windows10 , Windows11")
        self.log_append("")
        self.log_append("=== Please select WebPage URL ===")
        self.log_append("")

#=============================================================================================
# UI Helpers
#=============================================================================================
    def on_toggle_all(self):
        state = self.get_all_var.get()
        self.get_links_var.set(state)
        self.get_json_var.set(state)
        self.get_image_var.set(state)
        self.get_other_var.set(state)

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def log_append(self, message: str, level: str = "INFO"):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n", level)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.pump_gui()

    def pump_gui(self):
        try:
            self.root.update_idletasks()
            self.root.update()
        except tk.TclError:
            pass

#=============================================================================================
# 出力先を指定する処理
#=============================================================================================
def get_output_path(selection):
    if selection == "デスクトップ":
        # SHGetKnownFolderPath関数を使用してデスクトップのフルパスを取得する
        CSIDL_DESKTOP = 0x0000
        SHGFP_TYPE_CURRENT = 0
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_DESKTOP, None, SHGFP_TYPE_CURRENT, buf)
        output_path = buf.value

    elif selection == "このアプリと同じ場所":
        output_path = dir_name

    # フォルダを新規作成して作成しておく
    now_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    new_folder_path = os.path.join(output_path, f"output_{now_time}")
    os.makedirs(new_folder_path, exist_ok=True)
    output_path = new_folder_path
    return output_path

#=============================================================================================
# resourceファイルを探す関数　exe の親フォルダ配下の resources / img / assets / resource / _internal
#=============================================================================================
def _find_resource_file(filename: str) -> Path | None:
    try:
        script_dir = Path(__file__).resolve().parent
    except NameError:
        script_dir = Path.cwd()

    candidates: list[Path] = []

    # スクリプトと同じ場所
    candidates.append(script_dir / filename)

    # exe / スクリプトの親フォルダ + リソース候補フォルダ
    exe_parent = Path(getattr(sys, "executable", "")) .resolve().parent \
        if getattr(sys, "executable", None) else script_dir
    for base in {exe_parent, script_dir}:
        for folder in RESOURCE_DIR_CANDIDATES:
            candidates.append(base / folder / filename)

    # 親フォルダ直下
    candidates.append(exe_parent / filename)

    for c in candidates:
        if c.exists():
            return c
    return None


#=============================================================================================
# デバッグ用座標グリッド作成処理
#=============================================================================================
def enable_layout_debug(root):
    dbg = tk.Canvas(root, highlightthickness=0, bd=0)
    dbg.place(x=0, y=0, relwidth=1, relheight=1)
    tk.Misc.lower(dbg)

    info = tk.Label(root, text="x= , y= ", bg="white", fg="black")
    info.place(x=10, y=5)

    def redraw(event=None):
        dbg.delete("all")
        w = root.winfo_width()
        h = root.winfo_height()

        for x in range(0, w, 10):
            width = 2 if x % 50 == 0 else 1
            dbg.create_line(x, 0, x, h, fill="#dddddd", width=width)
            if x % 50 == 0:
                dbg.create_text(x + 2, 10, text=str(x), anchor="nw", fill="#888888")

        for y in range(0, h, 10):
            width = 2 if y % 50 == 0 else 1
            dbg.create_line(0, y, w, y, fill="#dddddd", width=width)
            if y % 50 == 0:
                dbg.create_text(2, y + 2, text=str(y), anchor="nw", fill="#888888")

    def on_click(e):
        info.config(text=f"x={e.x} , y={e.y}")
        print(f"[LAYOUT] x={e.x}, y={e.y}")

    root.bind("<Configure>", redraw)
    dbg.bind("<Button-1>", on_click)
    redraw()

#=============================================================================================
# エラーログの作成処理
#=============================================================================================
def error_message_activate(ex: Exception | None, window_title: str, error_description: str):
    if ex is None:
        # 例外なし（入力チェックなど）
        messagebox.showerror(window_title, error_description)
        return

    error_info = ""
    tb = traceback.TracebackException.from_exception(ex)

    for frame in tb.stack:
        error_info += "----------------------------\n"
        error_info += f"メソッド: {frame.name}\n"
        error_info += f"行番号  : {frame.lineno}\n"
        error_info += f"ファイル: {frame.filename}\n"

    messagebox.showerror(window_title, f"{error_description}:\n{error_info}\n{ex}")

#=============================================================================================
# 処理メインループ
#=============================================================================================
def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()

if __name__ == "__main__":
    main()