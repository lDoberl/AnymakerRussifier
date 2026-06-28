# -*- coding: utf-8 -*-
"""
Русификатор Anymaker Demo (v0.0.26)
GUI-патчер с выбором категорий перевода. Полностью обратимо.
"""
import os, sys, shutil, threading, traceback
import tkinter as tk
from tkinter import filedialog, messagebox

APP_TITLE    = "Русификатор Anymaker Demo"
GAME_VERSION = "v0.0.26"

# --- однобайтовый патч активного языка в game.gcl ---
GCL_REL        = "bin/game.gcl"
GCL_OFFSET     = 0x18b2f66
GCL_SIG_OFFSET = 0x18b2f46
GCL_SIG        = bytes.fromhex("48 83 ec 08 48 89 0c 24 8b 05 12 00 00 00".replace(" ", ""))
GCL_BYTE_EN    = 0x00
GCL_BYTE_RU    = 0x06

TSV_REL = "rom/languages.tsv"
MC_PREFIX = "script_element_"     # ключи блоков микроконтроллера

# JSON-категории: (ключ, подпись, [имя_ассета...])
JSON_CATS = [
    ("items",      "Предметы",                ["inventory_definitions.json"]),
    ("components", "Компоненты транспорта",    ["vehicle_component_definitions.json"]),
    ("creatures",  "Существа и животные",      ["creature_definitions.json", "zombie_definitions.json"]),
]
# Эти файлы всегда остаются английскими: внутриигровая книга-руководство
# рендерится шрифтом без кириллицы (русский текст в ней не отображается).
ALWAYS_EN = ["manual.json"]
JSON_PATHS = {
    "inventory_definitions.json":         "rom/data/inventory_definitions.json",
    "vehicle_component_definitions.json": "rom/data/vehicle_component_definitions.json",
    "creature_definitions.json":          "rom/data/creature_definitions.json",
    "zombie_definitions.json":            "rom/data/zombie_definitions.json",
    "manual.json":                        "rom/data/manual.json",
}

DEFAULT_PATHS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Anymaker Demo",
    r"C:\Program Files\Steam\steamapps\common\Anymaker Demo",
]


def resource_path(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", *parts)


def res_root(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def parse_steam_libraries():
    libs = []
    for steam in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            try:
                import re
                txt = open(vdf, encoding="utf-8", errors="ignore").read()
                for m in re.finditer(r'"path"\s*"([^"]+)"', txt):
                    libs.append(m.group(1).replace("\\\\", "\\"))
            except Exception:
                pass
    return libs


def auto_detect_game():
    cands = list(DEFAULT_PATHS)
    for lib in parse_steam_libraries():
        cands.append(os.path.join(lib, "steamapps", "common", "Anymaker Demo"))
    for c in cands:
        if is_valid_game(c):
            return c
    return ""


def is_valid_game(root):
    return bool(root) and os.path.isfile(os.path.join(root, GCL_REL)) \
        and os.path.isfile(os.path.join(root, "rom", "languages.tsv"))


def read_gcl_state(root):
    try:
        with open(os.path.join(root, GCL_REL), "rb") as f:
            f.seek(GCL_SIG_OFFSET); sig = f.read(len(GCL_SIG))
            f.seek(GCL_OFFSET);     b = f.read(1)
        if sig != GCL_SIG:
            return "badversion"
        return {bytes([GCL_BYTE_RU]): "ru", bytes([GCL_BYTE_EN]): "en"}.get(b, "unknown")
    except Exception:
        return "unknown"


def patch_gcl(root, target_byte):
    with open(os.path.join(root, GCL_REL), "r+b") as f:
        f.seek(GCL_SIG_OFFSET)
        if f.read(len(GCL_SIG)) != GCL_SIG:
            return False
        f.seek(GCL_OFFSET)
        f.write(bytes([target_byte]))
    return True


def build_languages_tsv(interface_on, mc_on):
    """Готовит содержимое languages.tsv под выбранные флаги (bytes, utf-8)."""
    if not interface_on:
        return open(resource_path("en", "languages.tsv"), "rb").read()
    raw = open(resource_path("ru", "languages.tsv"), "rb").read().decode("utf-8")
    if mc_on:
        return raw.encode("utf-8")
    # модули микроконтроллера на английском: в колонке ru ставим англ. значение (колонка 2)
    EN, RU = 2, 8
    out = []
    for i, line in enumerate(raw.split("\r\n")):
        if i == 0 or line == "":
            out.append(line); continue
        c = line.split("\t")
        if c[0].startswith(MC_PREFIX) and len(c) > RU:
            c[RU] = c[EN]
            line = "\t".join(c)
        out.append(line)
    return "\r\n".join(out).encode("utf-8")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(660, 600)
        # центрируем окно на экране (иначе на части систем открывается за краем)
        w, h = 700, 640
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        x = max(0, (min(sw, 1920) - w) // 2)
        y = 70
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.configure(bg="#1e1f22")
        self._busy = False
        self.game_dir = tk.StringVar(value=auto_detect_game())
        self.var_interface = tk.BooleanVar(value=True)
        self.var_mc        = tk.BooleanVar(value=True)
        self.json_vars     = {k: tk.BooleanVar(value=True) for k, _, _ in JSON_CATS}
        self._set_icon()
        self._build_ui()
        self.var_interface.trace_add("write", lambda *a: self._sync_mc_state())
        self._sync_mc_state()
        self.refresh_status()

    def _set_icon(self):
        # иконка окна и панели задач
        try:
            self._icon_img = tk.PhotoImage(file=res_root("icon.png"))
            self.iconphoto(True, self._icon_img)
        except Exception:
            pass
        try:
            self.iconbitmap(res_root("icon.ico"))
        except Exception:
            pass

    # ---------- UI ----------
    def _build_ui(self):
        FG, BG, SUB = "#f0f0f0", "#1e1f22", "#c8c8c8"
        tk.Label(self, text=f"Русификатор Anymaker Demo  ·  {GAME_VERSION}",
                 font=("Segoe UI", 15, "bold"), fg=FG, bg=BG).pack(anchor="w", padx=14, pady=(12, 4))

        frm = tk.Frame(self, bg=BG); frm.pack(fill="x", padx=14, pady=4)
        tk.Label(frm, text="Папка игры:", fg=SUB, bg=BG, font=("Segoe UI", 10)).pack(side="left")
        self.path_entry = tk.Entry(frm, textvariable=self.game_dir, font=("Segoe UI", 10),
                                   bg="#2b2d31", fg=FG, insertbackground=FG, relief="flat")
        self.path_entry.pack(side="left", fill="x", expand=True, padx=8, ipady=4)
        tk.Button(frm, text="Обзор…", command=self.browse, relief="flat", bg="#3a3d43",
                  fg=FG, activebackground="#4a4d53", font=("Segoe UI", 10)).pack(side="left")

        self.status_lbl = tk.Label(self, text="", font=("Segoe UI", 11, "bold"),
                                   fg=FG, bg=BG, anchor="w", justify="left")
        self.status_lbl.pack(fill="x", padx=14, pady=(6, 2))

        # --- категории ---
        box = tk.LabelFrame(self, text=" Что переводить ", fg=SUB, bg=BG,
                            font=("Segoe UI", 10, "bold"), relief="groove", bd=1)
        box.pack(fill="x", padx=14, pady=6)
        def mk(parent, var, text, indent=0):
            cb = tk.Checkbutton(parent, text=text, variable=var, onvalue=True, offvalue=False,
                                fg=FG, bg=BG, selectcolor="#2b2d31", activebackground=BG,
                                activeforeground=FG, font=("Segoe UI", 10), anchor="w")
            cb.pack(fill="x", padx=(14 + indent, 8), pady=1)
            return cb
        mk(box, self.var_interface, "Интерфейс и меню (меню, настройки, подсказки, категории)")
        self.cb_mc = mk(box, self.var_mc, "└ Модули микроконтроллера (блоки: если, повторить…)", indent=18)
        for key, label, _ in JSON_CATS:
            mk(box, self.json_vars[key], label)
        tk.Label(box, text="Руководство (книга) остаётся английским — в нём нет кириллического шрифта.",
                 fg="#7a7a7a", bg=BG, font=("Segoe UI", 8), anchor="w", justify="left").pack(
                 fill="x", padx=(14, 8), pady=(4, 2))

        sel = tk.Frame(self, bg=BG); sel.pack(fill="x", padx=14)
        tk.Button(sel, text="Выбрать всё", command=lambda: self._set_all(True), relief="flat",
                  bg="#3a3d43", fg=FG, font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        tk.Button(sel, text="Снять всё", command=lambda: self._set_all(False), relief="flat",
                  bg="#3a3d43", fg=FG, font=("Segoe UI", 9)).pack(side="left")

        btns = tk.Frame(self, bg=BG); btns.pack(fill="x", padx=14, pady=8)
        self.btn_ru = tk.Button(btns, text="🇷🇺  Русифицировать", command=lambda: self.run("ru"),
                                bg="#2e7d32", fg="white", activebackground="#388e3c",
                                font=("Segoe UI", 12, "bold"), relief="flat", height=2)
        self.btn_ru.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=4)
        self.btn_en = tk.Button(btns, text="↩  Вернуть оригинал", command=lambda: self.run("en"),
                                bg="#5a5d63", fg="white", activebackground="#6a6d73",
                                font=("Segoe UI", 12, "bold"), relief="flat", height=2)
        self.btn_en.pack(side="left", fill="x", expand=True, padx=(6, 0), ipady=4)

        tk.Label(self, text="Журнал:", fg="#9a9a9a", bg=BG, font=("Segoe UI", 9)).pack(anchor="w", padx=14)
        logf = tk.Frame(self, bg=BG); logf.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        self.log = tk.Text(logf, bg="#141517", fg="#cfd2d6", font=("Consolas", 9),
                           relief="flat", wrap="word", state="disabled", height=8)
        self.log.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(logf, command=self.log.yview); sb.pack(side="right", fill="y")
        self.log.config(yscrollcommand=sb.set)

        tk.Label(self, text="Закройте игру перед применением. Изменения вступают в силу при следующем запуске.",
                 fg="#7a7a7a", bg=BG, font=("Segoe UI", 8)).pack(side="bottom", pady=(0, 6))

    def _set_all(self, val):
        self.var_interface.set(val); self.var_mc.set(val)
        for v in self.json_vars.values(): v.set(val)

    def _sync_mc_state(self):
        # модули МК имеют смысл только при включённом интерфейсе (байт языка)
        self.cb_mc.config(state=("normal" if self.var_interface.get() else "disabled"))

    def log_line(self, msg, color="#cfd2d6"):
        def _():
            self.log.config(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.tag_add(color, "end-2l", "end-1l")
            self.log.tag_config(color, foreground=color)
            self.log.see("end"); self.log.config(state="disabled")
        self.after(0, _)

    def browse(self):
        d = filedialog.askdirectory(title="Выберите папку Anymaker Demo")
        if d:
            self.game_dir.set(d); self.refresh_status()

    def set_busy(self, busy):
        self._busy = busy
        st = "disabled" if busy else "normal"
        self.btn_ru.config(state=st); self.btn_en.config(state=st); self.path_entry.config(state=st)

    def refresh_status(self):
        root = self.game_dir.get().strip()
        if not is_valid_game(root):
            self.status_lbl.config(text="● Игра не найдена. Укажите папку Anymaker Demo (с bin\\game.gcl).", fg="#e57373"); return
        st = read_gcl_state(root)
        txt = {"badversion": ("● Версия game.gcl не совпадает (русификатор для " + GAME_VERSION + ").", "#ffb74d"),
               "ru": ("● Статус: интерфейс РУСИФИЦИРОВАН.", "#81c784"),
               "en": ("● Статус: интерфейс на ОРИГИНАЛЕ (английский).", "#90caf9"),
               "unknown": ("● Статус: неизвестно (game.gcl изменён иначе).", "#ffb74d")}[st]
        self.status_lbl.config(text=txt[0], fg=txt[1])

    # ---------- работа ----------
    def run(self, mode):
        if self._busy:
            return
        root = self.game_dir.get().strip()
        if not is_valid_game(root):
            messagebox.showerror(APP_TITLE, "Игра не найдена.\nУкажите папку Anymaker Demo (с bin\\game.gcl)."); return
        self.set_busy(True)
        threading.Thread(target=self._worker, args=(root, mode), daemon=True).start()

    def _copy(self, root, lang, asset_name):
        dst = os.path.join(root, JSON_PATHS[asset_name].replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(resource_path(lang, asset_name), dst)

    def _worker(self, root, mode):
        try:
            if mode == "en":   # полный откат
                self.log_line("=== ВОЗВРАТ ОРИГИНАЛА (всё) ===", "#ffd54f")
                with open(os.path.join(root, TSV_REL.replace("/", os.sep)), "wb") as f:
                    f.write(open(resource_path("en", "languages.tsv"), "rb").read())
                self.log_line("  ✓ rom/languages.tsv  (английский)")
                for name in JSON_PATHS:
                    self._copy(root, "en", name); self.log_line(f"  ✓ {JSON_PATHS[name]}")
                if patch_gcl(root, GCL_BYTE_EN):
                    self.log_line("  ✓ bin/game.gcl  (язык → английский)")
                else:
                    self._badversion(); return
                self.log_line("Готово. Перезапустите игру.", "#81c784")
                self._done("Возвращён оригинал (английский)!"); return

            # --- РУСИФИКАЦИЯ по выбранным галочкам ---
            interface_on = self.var_interface.get()
            mc_on        = self.var_mc.get()
            self.log_line("=== РУСИФИКАЦИЯ (выбранное) ===", "#ffd54f")

            # languages.tsv (интерфейс + модули МК)
            data = build_languages_tsv(interface_on, mc_on)
            with open(os.path.join(root, TSV_REL.replace("/", os.sep)), "wb") as f:
                f.write(data)
            self.log_line("  ✓ rom/languages.tsv  (интерфейс: %s, модули МК: %s)"
                          % ("рус" if interface_on else "ориг",
                             ("рус" if mc_on else "англ") if interface_on else "—"))

            # JSON-категории
            for key, label, names in JSON_CATS:
                lang = "ru" if self.json_vars[key].get() else "en"
                for name in names:
                    self._copy(root, lang, name)
                self.log_line(f"  ✓ {label}: {'русский' if lang=='ru' else 'оригинал'}")

            # руководство всегда английское (книга без кириллицы)
            for name in ALWAYS_EN:
                self._copy(root, "en", name)
            self.log_line("  ✓ Руководство: английский (книга не отображает кириллицу)", "#9a9a9a")

            # язык интерфейса (байт)
            target = GCL_BYTE_RU if interface_on else GCL_BYTE_EN
            if patch_gcl(root, target):
                self.log_line("  ✓ bin/game.gcl  (язык → %s)" % ("русский" if interface_on else "английский"))
            else:
                self._badversion(); return

            self.log_line("Готово. Перезапустите игру.", "#81c784")
            self._done("Русификация применена!")
        except PermissionError:
            self.log_line("  ✗ Нет доступа. Закройте игру и/или запустите от имени администратора.", "#e57373")
            self.after(0, lambda: messagebox.showerror(APP_TITLE,
                "Нет доступа к файлам игры.\nЗакройте игру и/или запустите русификатор от имени администратора."))
        except Exception as e:
            self.log_line("  ✗ Ошибка: " + str(e), "#e57373")
            self.log_line(traceback.format_exc())
            self.after(0, lambda: messagebox.showerror(APP_TITLE, "Ошибка:\n" + str(e)))
        finally:
            self.after(0, lambda: self.set_busy(False))
            self.after(0, self.refresh_status)

    def _badversion(self):
        self.log_line("  ✗ bin/game.gcl: сигнатура не совпала — другая версия игры. Байт языка не изменён.", "#e57373")
        self.after(0, lambda: messagebox.showwarning(APP_TITLE,
            "game.gcl другой версии — байт языка не изменён.\nОстальные файлы применены."))

    def _done(self, msg):
        self.after(0, lambda: messagebox.showinfo(APP_TITLE, msg + "\n\nПерезапустите игру, чтобы увидеть изменения."))


def _hide_console():
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


if __name__ == "__main__":
    _hide_console()
    App().mainloop()
