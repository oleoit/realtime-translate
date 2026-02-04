import os
import sys
import time
import threading
import re
import json
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog
import pyautogui
import pytesseract
import numpy as np
import cv2
from PIL import Image, ImageTk
import ctypes

# DPI Awareness เพื่อความคมชัดและจอมัวคลุมมิดหน้าจอจริง
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except:
    pass

from google import genai
from openai import OpenAI
from deep_translator import GoogleTranslator

# ==========================================
# 1. Resource & Config System
# ==========================================
def resource_path(relative_path):
    """ ค้นหา path ของไฟล์เวลาถูกแพ็คเป็น EXE """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

CONFIG_FILE = "config.json"

def load_config():
    defaults = {
        "api_key_gemini": "", "api_key_openai": "",
        "provider": "Google Translate", "model": "Standard",
        "tesseract_path": r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return {**defaults, **json.load(f)}
        except: return defaults
    return defaults

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

# ==========================================
# 2. Main App Class
# ==========================================
class MainApp:
    def __init__(self):
        self.config = load_config()
        pytesseract.pytesseract.tesseract_cmd = self.config["tesseract_path"]
        
        self.root = tk.Tk()
        self.root.title("OLELAB TRANSLATOR PRO")
        
        try:
            self.root.iconbitmap(resource_path("olelab.ico"))
        except: pass

        self.root.attributes("-alpha", 0.98, "-topmost", True)
        self.root.overrideredirect(True) 
        self.root.config(bg="#1e1e1e")
        
        self.cur_w, self.cur_h = 950, 750 
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f'{self.cur_w}x{self.cur_h}+{int(sw/2-self.cur_w/2)}+{int(sh/2-self.cur_h/2)}')
        
        self.selection_area = None
        self.is_auto = False
        self.is_processing = False
        self.panel_visible = True
        self.left_visible = True
        self.last_added_line_clean = ""

        self.colors = {
            "bg": "#1e1e1e", "header": "#252526", "primary": "#007acc",
            "success": "#28a745", "warning": "#d18616", "danger": "#c42b1c",
            "secondary": "#3e3e42", "text": "#cccccc", "white": "#ffffff"
        }

        self.setup_ui()
        self.sizegrip = ttk.Sizegrip(self.root)
        self.sizegrip.place(relx=1.0, rely=1.0, anchor="se")
        
        threading.Thread(target=self.bg_loop, daemon=True).start()

    def add_standard_bindings(self, widget, can_paste=True):
        """ แก้บั๊กถาวร: ดักจับ Keycode แทนชื่อปุ่ม เพื่อให้ใช้ได้ทุกภาษา """
        def handle_key_events(e):
            ctrl_pressed = e.state & 0x0004
            if ctrl_pressed:
                code = e.keycode
                if code == 86: # V / อ
                    if can_paste: widget.event_generate("<<Paste>>")
                    return "break"
                elif code == 67: # C / แ
                    widget.event_generate("<<Copy>>")
                    return "break"
                elif code == 65: # A / ฟ
                    if isinstance(widget, tk.Text): widget.tag_add("sel", "1.0", "end")
                    else: widget.selection_range(0, 'end')
                    return "break"
            return None

        widget.bind("<KeyPress>", handle_key_events)
        
        menu = tk.Menu(widget, tearoff=0, bg="#333333", fg="white", activebackground="#007acc")
        menu.add_command(label="คัดลอก (Ctrl+C)", command=lambda: widget.event_generate("<<Copy>>"))
        if can_paste:
            menu.add_command(label="วาง (Ctrl+V)", command=lambda: widget.event_generate("<<Paste>>"))
        menu.add_command(label="เลือกทั้งหมด (Ctrl+A)", command=lambda: [widget.tag_add("sel", "1.0", "end") if isinstance(widget, tk.Text) else widget.selection_range(0, 'end')])
        
        def show_menu(event):
            widget.focus_set()
            menu.tk_popup(event.x_root, event.y_root)
        widget.bind("<Button-3>", show_menu)

    def setup_ui(self):
        # --- Header ---
        self.header = tk.Frame(self.root, bg=self.colors["header"], height=35)
        self.header.pack(fill="x")
        try:
            logo_img = Image.open(resource_path("olelab.png")).resize((22, 22), Image.Resampling.LANCZOS)
            self.tk_logo = ImageTk.PhotoImage(logo_img)
            tk.Label(self.header, image=self.tk_logo, bg=self.colors["header"]).pack(side="left", padx=(10, 0))
        except: pass

        tk.Label(self.header, text=" OLELAB TRANSLATOR PRO", fg=self.colors["primary"], 
                 bg=self.colors["header"], font=("Segoe UI", 9, "bold")).pack(side="left")
        
        btn_close = tk.Label(self.header, text=" ✕ ", fg="white", bg=self.colors["header"], cursor="hand2", font=("Arial", 11))
        btn_close.pack(side="right", padx=5); btn_close.bind("<Button-1>", lambda e: self.root.destroy())

        btn_min = tk.Label(self.header, text=" — ", fg="white", bg=self.colors["header"], cursor="hand2", font=("Arial", 11))
        btn_min.pack(side="right", padx=5); btn_min.bind("<Button-1>", lambda e: self.on_minimize())

        self.btn_toggle_panel = tk.Label(self.header, text=" ▲ ", fg=self.colors["primary"], bg=self.colors["header"], cursor="hand2")
        self.btn_toggle_panel.pack(side="right", padx=10); self.btn_toggle_panel.bind("<Button-1>", self.toggle_top_panel)

        btn_set = tk.Label(self.header, text=" ⚙ ตั้งค่า API ", fg=self.colors["text"], bg=self.colors["header"], cursor="hand2", font=("Sarabun", 9))
        btn_set.pack(side="right", padx=10); btn_set.bind("<Button-1>", lambda e: self.open_settings())

        self.header.bind("<Button-1>", self.start_move); self.header.bind("<B1-Motion>", self.do_move)

        # --- Toolbar ---
        self.config_f = tk.Frame(self.root, bg=self.colors["bg"], pady=10); self.config_f.pack(fill="x")
        c_inner = tk.Frame(self.config_f, bg=self.colors["bg"]); c_inner.pack()
        self.lang_map = {"Thai": "tha+eng", "English": "eng", "Japanese": "jpn", "Chinese": "chi_sim", "Korean": "kor"}
        self.src_cb = ttk.Combobox(c_inner, values=list(self.lang_map.keys()), state="readonly", width=12); self.src_cb.set("English"); self.src_cb.grid(row=0, column=0)
        
        self.btn_swap_lang = tk.Label(c_inner, text=" ⇄ ", fg=self.colors["primary"], bg=self.colors["bg"], font=("Arial", 12, "bold"), cursor="hand2")
        self.btn_swap_lang.grid(row=0, column=1, padx=10)
        self.btn_swap_lang.bind("<Button-1>", lambda e: self.swap_languages())
        
        self.tgt_cb = ttk.Combobox(c_inner, values=list(self.lang_map.keys()), state="readonly", width=12); self.tgt_cb.set("Thai"); self.tgt_cb.grid(row=0, column=2)

        # --- Control Bar ---
        self.ctrl_f = tk.Frame(self.root, bg=self.colors["bg"]); self.ctrl_f.pack(fill="x", padx=20, pady=5)
        btn_data = [
            ("🎯 เลือกพื้นที่", self.run_selector, self.colors["primary"]),
            ("➤ แปลตอนนี้", lambda: self.perform_translation(manual=True), self.colors["success"]),
            ("🔄 แปล Auto", self.toggle_auto, self.colors["warning"]),
            ("🧹 เคลียร์หน้าจอ", self.clear_all, self.colors["secondary"]),
            ("💾 บันทึกไฟล์", self.save_text, self.colors["secondary"])
        ]
        for i, (txt, cmd, clr) in enumerate(btn_data):
            self.ctrl_f.columnconfigure(i, weight=1)
            b = tk.Button(self.ctrl_f, text=txt, command=cmd, bg=clr, fg="white", font=("Sarabun", 10, "bold"), bd=0, pady=10)
            b.grid(row=0, column=i, sticky="nsew", padx=3)
            if "Auto" in txt: self.btn_auto = b

        # --- Display Area ---
        self.display_container = tk.Frame(self.root, bg="#333333")
        self.display_container.pack(expand=True, fill="both", padx=20, pady=(10, 20))
        
        self.paned = tk.PanedWindow(self.display_container, orient=tk.HORIZONTAL, bg="#333333", sashwidth=4, bd=0)
        self.paned.pack(expand=True, fill="both")

        t_style = {"font": ("Sarabun", 11), "wrap": tk.WORD, "bd": 0, "padx": 15, "pady": 15, "insertbackground": "white"}
        self.left_txt = scrolledtext.ScrolledText(self.paned, **t_style, bg="#252526", fg="#cccccc")
        self.paned.add(self.left_txt, width=450); self.add_standard_bindings(self.left_txt, can_paste=True)

        self.right_txt = scrolledtext.ScrolledText(self.paned, **t_style, bg="#111111", fg="white", state='disabled')
        self.paned.add(self.right_txt, width=450); self.add_standard_bindings(self.right_txt, can_paste=False)

        # วางปุ่มย่อขยายหน้าต่าง ◀/▶ ให้ลอยทับแน่นอน (ปรับขนาดให้เล็กลง)
        self.btn_side = tk.Label(self.display_container, text="◀", font=("Arial", 8, "bold"), 
                                bg=self.colors["header"], fg=self.colors["primary"], width=1, cursor="hand2", padx=1, pady=2)
        self.btn_side.place(x=0, y=0); self.btn_side.lift()
        self.btn_side.bind("<Button-1>", lambda e: self.toggle_left_pane())

    def swap_languages(self):
        """ สลับภาษาต้นทางและปลายทาง """
        src, tgt = self.src_cb.get(), self.tgt_cb.get()
        self.src_cb.set(tgt); self.tgt_cb.set(src)

    def toggle_left_pane(self):
        if self.left_visible: self.paned.forget(self.left_txt); self.btn_side.config(text="▶")
        else: self.paned.add(self.left_txt, width=450, before=self.right_txt); self.btn_side.config(text="◀")
        self.left_visible = not self.left_visible; self.btn_side.lift()

    def open_settings(self):
        sw = tk.Toplevel(self.root); sw.withdraw()
        sw.title("Settings"); sw.config(bg="#252526")
        set_w, set_h = 420, 580
        m_x, m_y, m_w, m_h = self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width(), self.root.winfo_height()
        sw.geometry(f"{set_w}x{set_h}+{m_x + (m_w//2) - (set_w//2)}+{m_y + (m_h//2) - (set_h//2)}")
        sw.deiconify(); sw.transient(self.root); sw.grab_set(); sw.focus_force() 

        m_data = {"Google Translate":["Standard"],"Gemini":["gemini-2.0-flash","gemini-1.5-pro"],"ChatGPT":["o3-mini","gpt-4o"]}
        cb_prov = ttk.Combobox(sw, values=list(m_data.keys()), state="readonly")
        cb_prov.set(self.config["provider"]); cb_prov.pack(fill="x", padx=30, pady=15)
        cb_model = ttk.Combobox(sw, values=m_data[cb_prov.get()], state="readonly")
        cb_model.set(self.config["model"]); cb_model.pack(fill="x", padx=30, pady=5)
        cb_prov.bind("<<ComboboxSelected>>", lambda e: [cb_model.config(values=m_data[cb_prov.get()]), cb_model.set(m_data[cb_prov.get()][0])])

        self.entries = {}
        for label, key in [("Gemini API Key:", "api_key_gemini"), ("OpenAI API Key:", "api_key_openai")]:
            tk.Label(sw, text=label, fg="white", bg="#252526").pack(anchor="w", padx=30, pady=(10,0))
            ent = tk.Entry(sw, bg="#3e3e42", fg="white", insertbackground="white")
            ent.insert(0, self.config[key]); ent.pack(fill="x", padx=30, pady=5)
            self.add_standard_bindings(ent, can_paste=True); self.entries[key] = ent

        tk.Label(sw, text="Tesseract Path:", fg="white", bg="#252526").pack(anchor="w", padx=30, pady=(10,0))
        ent_tess = tk.Entry(sw, bg="#3e3e42", fg="white", insertbackground="white"); ent_tess.insert(0, self.config["tesseract_path"]); ent_tess.pack(fill="x", padx=30, pady=5)
        self.add_standard_bindings(ent_tess, can_paste=True); self.entries["tesseract_path"] = ent_tess

        tk.Button(sw, text="SAVE CONFIG", bg="#007acc", fg="white", font=("Sarabun", 10, "bold"), pady=10,
                  command=lambda: [self.config.update({"api_key_gemini":self.entries["api_key_gemini"].get(),"api_key_openai":self.entries["api_key_openai"].get(),"provider":cb_prov.get(),"model":cb_model.get(),"tesseract_path":self.entries["tesseract_path"].get()}), save_config(self.config), sw.destroy()]).pack(fill="x", padx=30, pady=30)

    def perform_translation(self, manual=False):
        if self.is_processing: return
        input_text = self.left_txt.get("1.0", tk.END).strip()
        if manual and input_text and not self.selection_area:
            self.translate_text_only(input_text.replace("● ", "").strip()); return
        if not self.selection_area: return
        self.is_processing = True
        try:
            shot = pyautogui.screenshot(region=self.selection_area)
            img = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2GRAY)
            img = cv2.threshold(cv2.resize(img, None, fx=2, fy=2), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            raw_ocr = pytesseract.image_to_string(img, lang=self.lang_map.get(self.src_cb.get(), "eng")).strip()
            if not raw_ocr: return
            clean = re.sub(r'[^a-zA-Zก-๙0-9]', '', raw_ocr).lower()
            if clean == self.last_added_line_clean: return
            self.last_added_line_clean = clean; translated = self.call_translator(raw_ocr); self.update_displays(raw_ocr, translated)
        finally: self.is_processing = False

    def translate_text_only(self, text):
        def run():
            self.is_processing = True; res = self.call_translator(text); self.update_displays(text, res, manual=True); self.is_processing = False
        threading.Thread(target=run, daemon=True).start()

    def update_displays(self, source, target, manual=False):
        if source:
            if manual: self.left_txt.delete("1.0", tk.END)
            p = "● "; self.left_txt.insert(tk.END, f"\n\n{p}{source}" if self.left_txt.get("1.0", tk.END).strip() else f"{p}{source}"); self.left_txt.see(tk.END)
        if target:
            self.right_txt.configure(state='normal'); p = "➤ "; self.right_txt.insert(tk.END, f"\n\n{p}{target}" if self.right_txt.get("1.0", tk.END).strip() else f"{p}{target}")
            self.right_txt.see(tk.END); self.right_txt.configure(state='disabled')

    def call_translator(self, text):
        prov, model, target_lang = self.config["provider"], self.config["model"], self.tgt_cb.get()
        prompt = f"Translate to {target_lang}. RULE: Output ONLY translation. NO greetings.\nTEXT:\n{text}"
        try:
            if prov == "Gemini":
                c = genai.Client(api_key=self.config["api_key_gemini"].strip()); return c.models.generate_content(model=model, contents=prompt).text.strip()
            elif prov == "ChatGPT":
                c = OpenAI(api_key=self.config["api_key_openai"].strip()); res = c.chat.completions.create(model=model, messages=[{"role":"user","content":prompt}], temperature=0); return res.choices[0].message.content.strip()
            return GoogleTranslator(source='auto', target=target_lang.lower()).translate(text)
        except Exception as e: return f"[Error]: {str(e)}"

    def on_minimize(self):
        self.root.overrideredirect(False); self.root.state('iconic')
        self.root.bind("<FocusIn>", lambda e: [self.root.overrideredirect(True), self.root.unbind("<FocusIn>")] if self.root.state() == 'normal' else None)
    def start_move(self, e): self.x, self.y = e.x, e.y
    def do_move(self, e): self.root.geometry(f"+{self.root.winfo_x()+(e.x-self.x)}+{self.root.winfo_y()+(e.y-self.y)}")
    def toggle_top_panel(self, e):
        if self.panel_visible: self.config_f.pack_forget(); self.ctrl_f.pack_forget(); self.btn_toggle_panel.config(text=" ▼ ")
        else: self.config_f.pack(fill="x", after=self.header); self.ctrl_f.pack(fill="x", padx=20, pady=5, after=self.config_f); self.btn_toggle_panel.config(text=" ▲ ")
        self.panel_visible = not self.panel_visible
    def clear_all(self):
        self.left_txt.delete('1.0', tk.END); self.right_txt.configure(state='normal'); self.right_txt.delete('1.0', tk.END); self.right_txt.configure(state='disabled'); self.last_added_line_clean = ""
    def save_text(self):
        p = filedialog.asksaveasfilename(defaultextension=".txt"); [open(p, "w", encoding="utf-8").write(self.right_txt.get('1.0', tk.END)) if p else None]
    def toggle_auto(self):
        self.is_auto = not self.is_auto; self.btn_auto.config(text="⏹ หยุด Auto" if self.is_auto else "🔄 แปล Auto", bg=self.colors["danger"] if self.is_auto else self.colors["warning"])
    def run_selector(self):
        self.root.withdraw(); s = AreaSelector(); self.root.wait_window(s.root); self.selection_area = s.selection if s.selection else self.selection_area; self.root.deiconify()
    def bg_loop(self):
        while True:
            if self.is_auto: self.perform_translation(); time.sleep(1.5)
            time.sleep(0.1)

class AreaSelector:
    def __init__(self):
        self.root = tk.Toplevel(); self.root.attributes("-fullscreen", True, "-alpha", 0.4, "-topmost", True); self.root.overrideredirect(True); self.root.config(bg="black")
        self.canvas = tk.Canvas(self.root, cursor="cross", bg="black", highlightthickness=0); self.canvas.pack(fill="both", expand=True)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight(); self.canvas.create_text(sw/2, 100, text="🎯 ลากพื้นที่เพื่อเลือก | กด ESC เพื่อยกเลิก", fill="white", font=("Sarabun", 26, "bold"))
        self.selection = None; self.root.focus_force(); self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.canvas.bind("<ButtonPress-1>", self.on_press); self.canvas.bind("<B1-Motion>", self.on_move); self.canvas.bind("<ButtonRelease-1>", self.on_release)
    def on_press(self, e): self.sx, self.sy = e.x, e.y; self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline='#007acc', width=3)
    def on_move(self, e): self.canvas.coords(self.rect, self.sx, self.sy, e.x, e.y)
    def on_release(self, e):
        c = self.canvas.coords(self.rect); self.selection = (int(min(c[0], c[2])), int(min(c[1], c[3])), int(abs(c[0]-c[2])), int(abs(c[1]-c[3]))) if c else None; self.root.destroy()

if __name__ == "__main__":
    app = MainApp(); app.root.mainloop()