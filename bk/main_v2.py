import os
import sys
import time
import threading
import re
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog
import pyautogui
import pytesseract
import numpy as np
import cv2
from PIL import Image, ImageTk
from google import genai
import difflib 

# ==========================================
# 1. Setup & Configuration
# ==========================================
API_KEY = "AIzaSyDAENsLci2M7RDE7Z8UrOR7j2J9sIIBiHo" # <--- อย่าลืมเปลี่ยนเป็น API Key ของคุณ
client = genai.Client(api_key=API_KEY.strip())

MODEL_ID = "gemini-2.0-flash" 
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

LANG_MAP = {"Thai": "tha+eng", "English": "eng", "Japanese": "jpn", "Chinese": "chi_sim", "Korean": "kor"}
LANG_LIST = list(LANG_MAP.keys())

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ==========================================
# 2. Main App Class
# ==========================================
class MainApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("OLELAB TRANSLATOR PRO")
        self.root.attributes("-alpha", 0.98, "-topmost", True)
        self.root.overrideredirect(True) 
        self.root.config(bg="#1e1e1e")
        
        self.cur_w, self.cur_h = 950, 750 
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.cur_x, self.cur_y = int(sw/2-self.cur_w/2), int(sh/2-self.cur_h/2)
        self.root.geometry(f'{self.cur_w}x{self.cur_h}+{self.cur_x}+{self.cur_y}')
        
        self.selection_area = None
        self.is_auto = False
        self.is_processing = False
        self.panel_visible = True
        self.last_raw_text = "" 
        self.left_visible = True

        self.colors = {
            "bg": "#1e1e1e", "header": "#252526", "primary": "#007acc",
            "success": "#28a745", "warning": "#d18616", "danger": "#c42b1c",
            "secondary": "#3e3e42", "text": "#cccccc", "white": "#ffffff"
        }

        # --- Window Icon ---
        try:
            icon_p = resource_path("olelab.png")
            icon_img = Image.open(icon_p)
            self.photo_icon = ImageTk.PhotoImage(icon_img)
            self.root.wm_iconphoto(True, self.photo_icon)
        except: pass

        # --- Header ---
        self.header = tk.Frame(self.root, bg=self.colors["header"], height=35)
        self.header.pack(fill="x")
        try:
            self.img_logo = Image.open(resource_path("olelab.png")).resize((20, 20), Image.LANCZOS)
            self.logo_photo = ImageTk.PhotoImage(self.img_logo)
            tk.Label(self.header, image=self.logo_photo, bg=self.colors["header"]).pack(side="left", padx=(10, 5))
        except: pass
        tk.Label(self.header, text="OLELAB TRANSLATOR PRO", fg=self.colors["primary"], bg=self.colors["header"], font=("Segoe UI", 9, "bold")).pack(side="left")
        
        btn_close = tk.Label(self.header, text=" ✕ ", fg=self.colors["white"], bg=self.colors["header"], font=("Arial", 10), cursor="hand2")
        btn_close.pack(side="right", padx=5)
        btn_close.bind("<Button-1>", lambda e: self.root.destroy())

        btn_min = tk.Label(self.header, text=" — ", fg=self.colors["white"], bg=self.colors["header"], font=("Arial", 10), cursor="hand2")
        btn_min.pack(side="right", padx=5)
        btn_min.bind("<Button-1>", lambda e: self.on_minimize())

        self.btn_toggle = tk.Label(self.header, text=" ▲ ", fg=self.colors["primary"], bg=self.colors["header"], font=("Arial", 10), cursor="hand2")
        self.btn_toggle.pack(side="right", padx=10)
        self.btn_toggle.bind("<Button-1>", self.toggle_panel)

        self.header.bind("<Button-1>", self.start_move); self.header.bind("<B1-Motion>", self.do_move)

        # --- Toolbar (English -> Thai) ---
        self.config_f = tk.Frame(self.root, bg=self.colors["bg"], pady=10); self.config_f.pack(fill="x")
        c_inner = tk.Frame(self.config_f, bg=self.colors["bg"]); c_inner.pack()
        self.src_cb = ttk.Combobox(c_inner, values=LANG_LIST, state="readonly", width=12)
        self.src_cb.set("English") 
        self.src_cb.grid(row=0, column=0)
        
        self.btn_swap = tk.Label(c_inner, text=" ⇄ ", fg=self.colors["primary"], bg=self.colors["bg"], font=("Arial", 12, "bold"), cursor="hand2")
        self.btn_swap.grid(row=0, column=1, padx=10)
        self.btn_swap.bind("<Button-1>", lambda e: self.swap_languages())
        
        self.tgt_cb = ttk.Combobox(c_inner, values=LANG_LIST, state="readonly", width=12)
        self.tgt_cb.set("Thai") 
        self.tgt_cb.grid(row=0, column=2)

        # --- Control Bar ---
        self.ctrl_f = tk.Frame(self.root, bg=self.colors["bg"]); self.ctrl_f.pack(fill="x", padx=20, pady=5)
        for i in range(5): self.ctrl_f.columnconfigure(i, weight=1)
        
        btn_data = [
            ("🎯 พื้นที่", self.run_selector, self.colors["primary"]),
            ("➤ แปลตอนนี้", lambda: self.perform_translation(True), self.colors["success"]),
            ("🔄 แปล Auto", self.toggle_auto, self.colors["warning"]),
            ("🧹 เคลียร์", self.clear_all, self.colors["secondary"]),
            ("💾 บันทึก", self.save_text, self.colors["secondary"])
        ]
        
        for i, (txt, cmd, clr) in enumerate(btn_data):
            b = tk.Button(self.ctrl_f, text=txt, command=cmd, bg=clr, fg="white", font=("Sarabun", 10, "bold"), bd=0, pady=10, cursor="hand2")
            b.grid(row=0, column=i, sticky="nsew", padx=3)
            if "Auto" in txt: self.btn_auto = b

        # --- Display Area ---
        self.display_container = tk.Frame(self.root, bg="#333333")
        self.display_container.pack(expand=True, fill="both", padx=20, pady=10)

        self.paned = tk.PanedWindow(self.display_container, orient=tk.HORIZONTAL, bg="#333333", sashwidth=4, bd=0)
        self.paned.pack(expand=True, fill="both")

        t_style = {"font": ("Sarabun", 11), "wrap": tk.WORD, "bd": 0, "padx": 15, "pady": 15, "bg": "#252526", "fg": "#cccccc", "insertbackground": "white"}
        self.left_txt = scrolledtext.ScrolledText(self.paned, **t_style)
        self.paned.add(self.left_txt, width=450)
        
        t_style.update({"bg": "#111111", "fg": "white"})
        self.right_txt = scrolledtext.ScrolledText(self.paned, **t_style)
        self.paned.add(self.right_txt, width=450)

        # --- ปุ่มลูกศรจิ๋ว มุมซ้ายบน (ลดขนาดลงอีกครึ่งหนึ่ง) ---
        self.side_toggle = tk.Button(self.display_container, text="◀", font=("Arial", 7, "bold"), 
                                    bg=self.colors["primary"], fg="white", bd=0, 
                                    width=1, height=1, padx=0, pady=0, # รีดขนาดให้เล็กสุด
                                    cursor="hand2", command=self.toggle_left_side)
        self.side_toggle.place(relx=0.002, rely=0.005, anchor="nw") # ชิดมุมขึ้นอีกนิด
        self.side_toggle.lift()

        # Context Menu
        self.setup_context_menu(self.left_txt); self.setup_context_menu(self.right_txt)
        self.sizegrip = ttk.Sizegrip(self.root); self.sizegrip.place(relx=1.0, rely=1.0, anchor="se")
        
        threading.Thread(target=self.bg_loop, daemon=True).start()

    # --- ฟังก์ชันจัดการย่อซ้าย ---
    def toggle_left_side(self):
        if self.left_visible:
            self.paned.forget(self.left_txt)
            self.side_toggle.config(text="▶")
            self.left_visible = False
        else:
            self.paned.forget(self.right_txt)
            self.paned.add(self.left_txt, width=450)
            self.paned.add(self.right_txt, width=450)
            self.side_toggle.config(text="◀")
            self.left_visible = True
        self.side_toggle.lift()

    # --- ระบบคลิกขวาและคีย์ลัด ---
    def setup_context_menu(self, widget):
        menu = tk.Menu(self.root, tearoff=0, bg="#333333", fg="white", activebackground="#007acc")
        menu.add_command(label="คัดลอก (Copy)", command=lambda: self.custom_copy(widget))
        menu.add_command(label="วาง (Paste)", command=lambda: self.custom_paste(widget))
        menu.add_separator()
        menu.add_command(label="เลือกทั้งหมด", command=lambda: widget.tag_add("sel", "1.0", "end"))
        widget.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))
        widget.bind("<Control-c>", lambda e: self.custom_copy(widget))
        widget.bind("<Control-v>", lambda e: self.custom_paste(widget))
        widget.bind("<Control-a>", lambda e: [widget.tag_add("sel", "1.0", "end"), "break"][1])

    def custom_copy(self, widget):
        try: selected = widget.get("sel.first", "sel.last")
        except: selected = widget.get("1.0", tk.END).strip()
        if selected: self.root.clipboard_clear(); self.root.clipboard_append(selected)
        return "break"

    def custom_paste(self, widget):
        try:
            text = self.root.clipboard_get()
            widget.configure(state='normal'); widget.insert(tk.INSERT, text); widget.configure(state='disabled')
        except: pass
        return "break"

    def swap_languages(self):
        s, t = self.src_cb.get(), self.tgt_cb.get()
        self.src_cb.set(t); self.tgt_cb.set(s)

    # --- OCR & Translation ---
    def perform_translation(self, manual=False):
        if not self.selection_area or self.is_processing: return
        self.is_processing = True
        try:
            win_x, win_y = self.root.winfo_x(), self.root.winfo_y()
            win_w, win_h = self.root.winfo_width(), self.root.winfo_height()
            sel_x, sel_y, sel_w, sel_h = self.selection_area
            overlap = not (sel_x > win_x + win_w or sel_x + sel_w < win_x or sel_y > win_y + win_h or sel_y + sel_h < win_y)
            if overlap:
                self.root.attributes("-alpha", 0.0); self.root.update_idletasks()
                shot = pyautogui.screenshot(region=self.selection_area); self.root.attributes("-alpha", 0.98)
            else: shot = pyautogui.screenshot(region=self.selection_area)
            img = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2GRAY)
            img = cv2.resize(img, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            ocr_lang = LANG_MAP.get(self.src_cb.get(), "tha+eng")
            raw_ocr = pytesseract.image_to_string(img, lang=ocr_lang, config='--psm 3').strip()
            raw = "\n".join([re.sub(r'(?<=[ก-๙])\s+(?=[ก-๙])', '', line).strip() for line in raw_ocr.splitlines() if line.strip()])
            is_new = raw != self.last_raw_text and difflib.SequenceMatcher(None, raw, self.last_raw_text).ratio() < 0.95
            if raw and (manual or is_new):
                self.last_raw_text = raw
                res = client.models.generate_content(model=MODEL_ID, contents=f"Translate to {self.tgt_cb.get()}. Maintain line structure. Return ONLY translation.\n\n{raw}")
                translated = res.text.strip()
                if translated:
                    for txt_w, symbol, content in [(self.left_txt, "●", raw), (self.right_txt, "➤", translated)]:
                        txt_w.configure(state='normal')
                        if txt_w.get("1.0", tk.END).strip(): txt_w.insert(tk.END, "\n\n")
                        txt_w.insert(tk.END, f"{symbol} {content}"); txt_w.see(tk.END); txt_w.configure(state='disabled')
        except: pass
        finally: self.is_processing = False

    def run_selector(self):
        self.root.withdraw(); s = AreaSelector(); self.root.wait_window(s.root)
        if s.selection: self.selection_area = s.selection
        self.root.deiconify()

    def on_minimize(self):
        self.root.update_idletasks(); self.root.overrideredirect(False); self.root.state('iconic')
        self.root.bind("<FocusIn>", lambda e: self.root.overrideredirect(True) if self.root.state() == 'normal' else None)
    def start_move(self, e): self.x, self.y = e.x, e.y
    def do_move(self, e): nx, ny = self.root.winfo_x()+(e.x-self.x), self.root.winfo_y()+(e.y-self.y); self.root.geometry(f"+{nx}+{ny}")
    def toggle_panel(self, event):
        if self.panel_visible: self.config_f.pack_forget(); self.ctrl_f.pack_forget(); self.btn_toggle.config(text=" ▼ ")
        else: self.config_f.pack(fill="x", after=self.header); self.ctrl_f.pack(fill="x", padx=20, pady=5, after=self.config_f); self.btn_toggle.config(text=" ▲ ")
        self.panel_visible = not self.panel_visible
    def clear_all(self):
        for t in [self.left_txt, self.right_txt]: t.configure(state='normal'); t.delete('1.0', tk.END); t.configure(state='disabled')
        self.last_raw_text = ""
    def save_text(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f: f.write(f"ORIGINAL:\n{self.left_txt.get('1.0', tk.END)}\n\nTRANSLATION:\n{self.right_txt.get('1.0', tk.END)}")
    def toggle_auto(self):
        self.is_auto = not self.is_auto
        self.btn_auto.config(text="⏹ หยุด Auto" if self.is_auto else "🔄 แปล Auto", bg=self.colors["danger"] if self.is_auto else self.colors["warning"])
    def bg_loop(self):
        while True:
            if self.is_auto: self.perform_translation(); time.sleep(1.0)
            time.sleep(0.1)

class AreaSelector:
    # ... (ส่วนนี้คงเดิม)
    def __init__(self):
        self.root = tk.Toplevel(); self.root.attributes('-alpha', 0.4, '-fullscreen', True, "-topmost", True)
        self.root.overrideredirect(True); self.root.config(bg="black")
        self.canvas = tk.Canvas(self.root, cursor="cross", bg="black", highlightthickness=0); self.canvas.pack(fill="both", expand=True)
        self.selection = None
        sw = self.root.winfo_screenwidth()
        self.canvas.create_text(sw/2, 50, text="ลากเพื่อเลือกพื้นที่ | กด ESC เพื่อยกเลิก", fill="white", font=("Sarabun", 16, "bold"))
        self.root.focus_force(); self.root.bind_all("<Escape>", lambda e: self.root.destroy())
        self.canvas.bind("<ButtonPress-1>", self.on_press); self.canvas.bind("<B1-Motion>", self.on_move); self.canvas.bind("<ButtonRelease-1>", self.on_release)
    def on_press(self, e): self.sx, self.sy = e.x, e.y; self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline='#007acc', width=2)
    def on_move(self, e): self.canvas.coords(self.rect, self.sx, self.sy, e.x, e.y)
    def on_release(self, e):
        w, h = abs(self.sx - e.x), abs(self.sy - e.y)
        if w > 5 and h > 5: self.selection = (min(self.sx, e.x), min(self.sy, e.y), w, h); self.root.destroy()

if __name__ == "__main__":
    app = MainApp(); app.root.mainloop()