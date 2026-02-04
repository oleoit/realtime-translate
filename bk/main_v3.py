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

# ป้องกันปัญหาหน้าจอ Scaling เพื่อให้จอดำคลุมมิดหน้าจอจริง
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except:
    pass

# AI Libraries
from google import genai
from openai import OpenAI
from deep_translator import GoogleTranslator

# ==========================================
# 1. Configuration System
# ==========================================
CONFIG_FILE = "config.json"

def load_config():
    defaults = {
        "api_key_gemini": "",
        "api_key_openai": "",
        "provider": "Gemini",
        "model": "gemini-2.0-flash",
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
        self.sentence_cache = set()
        self.last_added_line_clean = ""

        self.colors = {
            "bg": "#1e1e1e", "header": "#252526", "primary": "#007acc",
            "success": "#28a745", "warning": "#d18616", "danger": "#c42b1c",
            "secondary": "#3e3e42", "text": "#cccccc", "white": "#ffffff"
        }

        self.setup_ui()
        # นำ Sizegrip กลับมาที่มุมขวาล่างตามคำขอ
        self.sizegrip = ttk.Sizegrip(self.root)
        self.sizegrip.place(relx=1.0, rely=1.0, anchor="se")
        
        threading.Thread(target=self.bg_loop, daemon=True).start()

    def setup_ui(self):
        # --- Header ---
        self.header = tk.Frame(self.root, bg=self.colors["header"], height=35)
        self.header.pack(fill="x")
        tk.Label(self.header, text="  OLELAB TRANSLATOR PRO", fg=self.colors["primary"], 
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
        tk.Label(c_inner, text=" ⇄ ", fg=self.colors["primary"], bg=self.colors["bg"], font=("Arial", 12, "bold")).grid(row=0, column=1, padx=10)
        self.tgt_cb = ttk.Combobox(c_inner, values=list(self.lang_map.keys()), state="readonly", width=12); self.tgt_cb.set("Thai"); self.tgt_cb.grid(row=0, column=2)

        # --- Control Bar ---
        self.ctrl_f = tk.Frame(self.root, bg=self.colors["bg"]); self.ctrl_f.pack(fill="x", padx=20, pady=5)
        btn_data = [
            ("🎯 เลือกพื้นที่", self.run_selector, self.colors["primary"]),
            ("➤ แปลตอนนี้", lambda: self.perform_translation(True), self.colors["success"]),
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
        
        self.btn_side = tk.Button(self.display_container, text="◀", font=("Arial", 8, "bold"), 
                                 bg=self.colors["header"], fg=self.colors["primary"], bd=0, width=2, height=1, 
                                 cursor="hand2", command=self.toggle_left_pane)
        self.btn_side.place(x=0, y=0); self.btn_side.lift()

        self.paned = tk.PanedWindow(self.display_container, orient=tk.HORIZONTAL, bg="#333333", sashwidth=4, bd=0)
        self.paned.pack(expand=True, fill="both", padx=(15, 0))

        t_style = {"font": ("Sarabun", 11), "wrap": tk.WORD, "bd": 0, "padx": 15, "pady": 15, "bg": "#252526", "fg": "#cccccc"}
        self.left_txt = scrolledtext.ScrolledText(self.paned, **t_style); self.paned.add(self.left_txt, width=450)
        t_style.update({"bg": "#111111", "fg": "white"})
        self.right_txt = scrolledtext.ScrolledText(self.paned, **t_style); self.paned.add(self.right_txt, width=450)

    # ==========================================
    # 3. Window Control & Logic
    # ==========================================
    def on_minimize(self):
        self.root.overrideredirect(False); self.root.state('iconic')
        self.root.bind("<FocusIn>", lambda e: [self.root.overrideredirect(True), self.root.unbind("<FocusIn>")] if self.root.state() == 'normal' else None)

    def toggle_left_pane(self):
        if self.left_visible: self.paned.forget(self.left_txt); self.btn_side.config(text="▶")
        else: self.paned.add(self.left_txt, width=450, before=self.right_txt); self.btn_side.config(text="◀")
        self.left_visible = not self.left_visible

    def toggle_top_panel(self, e):
        if self.panel_visible: self.config_f.pack_forget(); self.ctrl_f.pack_forget(); self.btn_toggle_panel.config(text=" ▼ ")
        else: self.config_f.pack(fill="x", after=self.header); self.ctrl_f.pack(fill="x", padx=20, pady=5, after=self.config_f); self.btn_toggle_panel.config(text=" ▲ ")
        self.panel_visible = not self.panel_visible

    # ==========================================
    # 4. Translation Engine (Filter Included)
    # ==========================================
    def clean_ai_response(self, text):
        # ลบประโยคเกริ่นนำที่ AI ชอบแอบเติมมาให้เด็ดขาด
        bad_phrases = ["แน่นอน", "นี่คือคำแปล", "แปลได้ว่า", "บรรทัดต่อบรรทัด", "Certainly", "Here is", "Translated text:"]
        lines = text.splitlines()
        filtered = [l for l in lines if not any(p in l for p in bad_phrases) or len(l) > 100]
        return "\n".join(filtered).strip()

    def call_translator(self, text):
        prov, model = self.config["provider"], self.config["model"]
        target_lang = self.tgt_cb.get()
        prompt = (f"Translate to {target_lang}. RULE: Output ONLY translation. "
                  f"NO greetings. NO explanations.\nTEXT:\n{text}")
        try:
            res_text = ""
            if prov == "Gemini":
                if not self.config["api_key_gemini"]: return "[Error]: Key missing"
                c = genai.Client(api_key=self.config["api_key_gemini"].strip())
                res_text = c.models.generate_content(model=model, contents=prompt).text
            elif prov == "ChatGPT":
                if not self.config["api_key_openai"]: return "[Error]: Key missing"
                c = OpenAI(api_key=self.config["api_key_openai"].strip())
                res = c.chat.completions.create(model=model, messages=[{"role":"system","content":"Literal translator."}, {"role":"user","content":prompt}], temperature=0)
                res_text = res.choices[0].message.content
            elif prov == "Google Translate":
                return GoogleTranslator(source='auto', target=target_lang.lower()).translate(text)
            
            return self.clean_ai_response(res_text)
        except Exception as e: return f"[Error]: {str(e)}"

    # ==========================================
    # 5. Core Processing Methods
    # ==========================================
    def perform_translation(self, manual=False):
        if not self.selection_area or self.is_processing: return
        self.is_processing = True
        try:
            shot = pyautogui.screenshot(region=self.selection_area)
            img = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2GRAY)
            img = cv2.threshold(cv2.resize(img, None, fx=2, fy=2), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            raw_ocr = pytesseract.image_to_string(img, lang=self.lang_map.get(self.src_cb.get(), "eng")).strip()
            
            lines = [l.strip() for l in raw_ocr.splitlines() if l.strip()]
            new_lines = []
            for l in lines:
                clean = re.sub(r'[^a-zA-Zก-๙0-9]', '', l).lower()
                if clean != self.last_added_line_clean and clean not in self.sentence_cache:
                    new_lines.append(l); self.last_added_line_clean = clean
                    if len(clean) > 15: self.sentence_cache.add(clean)
            if not new_lines: return
            input_text = "\n".join(new_lines); translated = self.call_translator(input_text)
            if translated:
                for txt_w, sym, content in [(self.left_txt, "●", input_text), (self.right_txt, "➤", translated)]:
                    txt_w.configure(state='normal'); txt_w.insert(tk.END, f"\n\n{sym} {content}" if txt_w.get("1.0", tk.END).strip() else f"{sym} {content}")
                    txt_w.see(tk.END); txt_w.configure(state='disabled')
        finally: self.is_processing = False

    def open_settings(self):
        sw = tk.Toplevel(self.root); sw.title("Settings"); sw.geometry("420x550"); sw.config(bg="#252526"); sw.grab_set()
        m_data = {"Gemini":["gemini-2.0-flash","gemini-1.5-pro"],"ChatGPT":["o3-mini","gpt-4o"],"Google Translate":["Standard"]}
        
        cb_prov = ttk.Combobox(sw, values=list(m_data.keys()), state="readonly")
        cb_prov.set(self.config["provider"]); cb_prov.pack(fill="x", padx=30, pady=15)
        cb_model = ttk.Combobox(sw, values=m_data[cb_prov.get()], state="readonly")
        cb_model.set(self.config["model"]); cb_model.pack(fill="x", padx=30, pady=5)
        cb_prov.bind("<<ComboboxSelected>>", lambda e: [cb_model.config(values=m_data[cb_prov.get()]), cb_model.set(m_data[cb_prov.get()][0])])

        ent_gem = tk.Entry(sw, bg="#3e3e42", fg="white"); ent_gem.insert(0, self.config["api_key_gemini"]); ent_gem.pack(fill="x", padx=30, pady=10)
        ent_gpt = tk.Entry(sw, bg="#3e3e42", fg="white"); ent_gpt.insert(0, self.config["api_key_openai"]); ent_gpt.pack(fill="x", padx=30, pady=10)
        ent_tess = tk.Entry(sw, bg="#3e3e42", fg="white"); ent_tess.insert(0, self.config["tesseract_path"]); ent_tess.pack(fill="x", padx=30, pady=10)
        
        tk.Button(sw, text="SAVE CONFIG", command=lambda: [self.config.update({"api_key_gemini":ent_gem.get(),"api_key_openai":ent_gpt.get(),"provider":cb_prov.get(),"model":cb_model.get(),"tesseract_path":ent_tess.get()}), save_config(self.config), sw.destroy()]).pack(fill="x", padx=30, pady=20)

    def start_move(self, e): self.x, self.y = e.x, e.y
    def do_move(self, e): self.root.geometry(f"+{self.root.winfo_x()+(e.x-self.x)}+{self.root.winfo_y()+(e.y-self.y)}")
    def clear_all(self):
        for t in [self.left_txt, self.right_txt]: t.configure(state='normal'); t.delete('1.0', tk.END); t.configure(state='disabled')
        self.sentence_cache.clear(); self.last_added_line_clean = ""
    def save_text(self):
        p = filedialog.asksaveasfilename(defaultextension=".txt"); [open(p, "w", encoding="utf-8").write(self.right_txt.get('1.0', tk.END)) if p else None]
    def toggle_auto(self):
        self.is_auto = not self.is_auto; self.btn_auto.config(text="⏹ หยุด Auto" if self.is_auto else "🔄 แปล Auto", bg=self.colors["danger"] if self.is_auto else self.colors["warning"])
    def run_selector(self):
        self.root.withdraw(); s = AreaSelector(); self.root.wait_window(s.root)
        if s.selection: self.selection_area = s.selection
        self.root.deiconify()
    def bg_loop(self):
        while True:
            if self.is_auto: self.perform_translation(); time.sleep(1.3)
            time.sleep(0.1)

# ==========================================
# 6. Fixed Area Selector (DPI Aware)
# ==========================================
class AreaSelector:
    def __init__(self):
        self.root = tk.Toplevel()
        # ใช้ -fullscreen เพื่อให้จอดำคลุมหน้าจอทั้งหมด
        self.root.attributes("-fullscreen", True, "-alpha", 0.4, "-topmost", True)
        self.root.overrideredirect(True); self.root.config(bg="black")
        self.canvas = tk.Canvas(self.root, cursor="cross", bg="black", highlightthickness=0); self.canvas.pack(fill="both", expand=True)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.canvas.create_text(sw/2, 50, text="🎯 ลากพื้นที่เพื่อเลือก | กด ESC เพื่อยกเลิก", fill="white", font=("Sarabun", 24, "bold"))
        self.selection = None
        self.root.focus_force(); self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.canvas.bind("<ButtonPress-1>", self.on_press); self.canvas.bind("<B1-Motion>", self.on_move); self.canvas.bind("<ButtonRelease-1>", self.on_release)
    def on_press(self, e): 
        self.sx, self.sy = e.x, e.y
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline='#007acc', width=3)
    def on_move(self, e): self.canvas.coords(self.rect, self.sx, self.sy, e.x, e.y)
    def on_release(self, e):
        x1, y1, x2, y2 = self.canvas.coords(self.rect)
        w, h = abs(x1 - x2), abs(y1 - y2)
        if w > 5 and h > 5:
            self.selection = (int(min(x1, x2)), int(min(y1, y2)), int(w), int(h))
            self.root.destroy()

if __name__ == "__main__":
    app = MainApp(); app.root.mainloop()