#pip install pymupdf

import fitz  # PyMuPDF
import io
import os
import tempfile
import copy
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
from PIL import Image, ImageTk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = None
    TkinterDnD = None


class SimplePDFEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Quick PDF Notation Editor")
        self.root.geometry("1100x800")
        
        # State variables
        self.doc = None
        self.current_page_idx = 0
        self.zoom_scale = 1.3  # Increase for higher clarity viewing
        self.edit_mode = tk.StringVar(value="erase")
        self.erased_regions = {}
        self.pending_move = None
        self.drag_start = None
        self.drag_start_page = None
        self.selection_item = None
        self.rendered_size = (0, 0)
        self.timeline_items = {}
        self.timeline_drag_source = None
        self.timeline_drag_start_x = None
        self.timeline_drag_moved = False
        self.timeline_drag_marker = None
        self.history = []
        self.redo_history = []
        self.history_limit = 10
        self.temp_copy_var = tk.BooleanVar(value=True)
        self.temp_copy_path = None
        self.has_unsaved_changes = False
        self.text_font_var = tk.StringVar(value="Helvetica Bold")
        self.text_size_var = tk.IntVar(value=14)
        self.text_color = "#c53030"
        self.text_box_rect = None
        self.text_box_page_idx = None
        
        # Style Configuration
        self.setup_styles()
        
        # Build UI layout
        self.create_widgets()
        self.bind_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TButton", font=("Helvetica", 10), padding=6)
        style.configure("Action.TButton", font=("Helvetica", 10, "bold"), background="#007acc", foreground="white")
        style.map("Action.TButton", background=[('active', '#005999')])

    def create_widgets(self):
        # --- Top Menu Toolbar ---
        toolbar = ttk.Frame(self.root, padding=8, relief="raised")
        toolbar.pack(side=tk.TOP, fill=tk.X)
        
        ttk.Button(toolbar, text="📂 Open PDF", command=self.open_pdf).pack(side=tk.LEFT, padx=5)
        self.insert_btn = ttk.Button(
            toolbar, text="Insert PDF Pages", command=self.choose_pdf_to_insert, state=tk.DISABLED
        )
        self.insert_btn.pack(side=tk.LEFT, padx=5)
        self.save_btn = ttk.Button(toolbar, text="💾 Save Document As", style="Action.TButton", command=self.save_pdf, state=tk.DISABLED)
        self.save_btn.pack(side=tk.LEFT, padx=5)
        self.undo_btn = ttk.Button(toolbar, text="Undo", command=self.undo, state=tk.DISABLED)
        self.undo_btn.pack(side=tk.LEFT, padx=2)
        self.redo_btn = ttk.Button(toolbar, text="Redo", command=self.redo, state=tk.DISABLED)
        self.redo_btn.pack(side=tk.LEFT, padx=2)
        ttk.Checkbutton(
            toolbar, text="Temporary work copy", variable=self.temp_copy_var,
            command=self.toggle_temp_copy
        ).pack(side=tk.LEFT, padx=(8, 2))
        
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        
        self.prev_btn = ttk.Button(toolbar, text="◀ Previous", command=self.prev_page, state=tk.DISABLED)
        self.prev_btn.pack(side=tk.LEFT, padx=2)
        
        self.page_label = ttk.Label(toolbar, text="Page: 0 / 0", font=("Helvetica", 10, "bold"))
        self.page_label.pack(side=tk.LEFT, padx=10)
        
        self.next_btn = ttk.Button(toolbar, text="Next ▶", command=self.next_page, state=tk.DISABLED)
        self.next_btn.pack(side=tk.LEFT, padx=2)

        # --- Main Workspace Splitter ---
        paned_window = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left Column: Document Canvas Viewer
        canvas_frame = ttk.Frame(paned_window, relief="sunken")
        paned_window.add(canvas_frame, weight=3)
        
        # Adding scrollbars to canvas for oversized PDFs
        self.v_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL)
        self.h_scroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
        
        self.canvas = tk.Canvas(
            canvas_frame, 
            bg="#525659", 
            xscrollcommand=self.h_scroll.set, 
            yscrollcommand=self.v_scroll.set,
            highlightthickness=0
        )
        
        self.v_scroll.config(command=self.canvas.yview)
        self.h_scroll.config(command=self.canvas.xview)
        
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self.begin_canvas_action)
        self.canvas.bind("<B1-Motion>", self.update_canvas_action)
        self.canvas.bind("<ButtonRelease-1>", self.finish_canvas_action)

        # Right Column: Scrollable Side Control Editing Tools
        control_frame = ttk.Frame(paned_window, width=320, relief="flat")
        paned_window.add(control_frame, weight=1)
        control_canvas = tk.Canvas(control_frame, highlightthickness=0, width=300)
        self.control_canvas = control_canvas
        control_scroll = ttk.Scrollbar(
            control_frame, orient=tk.VERTICAL, command=control_canvas.yview
        )
        control_canvas.configure(yscrollcommand=control_scroll.set)
        control_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        control_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        control_panel = ttk.Frame(control_canvas, padding=15)
        control_window = control_canvas.create_window(
            (0, 0), window=control_panel, anchor=tk.NW
        )
        control_panel.bind(
            "<Configure>",
            lambda _event: control_canvas.configure(
                scrollregion=control_canvas.bbox("all")
            )
        )
        control_canvas.bind(
            "<Configure>",
            lambda event: control_canvas.itemconfigure(
                control_window, width=event.width
            )
        )
        control_canvas.bind("<Enter>", self._bind_control_mousewheel)
        control_canvas.bind("<Leave>", self._unbind_control_mousewheel)

        # Tool 1: Text Box Notation Editor
        ttk.Label(control_panel, text="📝 Page Notation Text:", font=("Helvetica", 11, "bold")).pack(anchor=tk.W, pady=(0, 5))
        self.notation_box = tk.Text(control_panel, height=8, font=("Helvetica", 10), wrap=tk.WORD, bd=1, relief="solid")
        self.notation_box.pack(fill=tk.X, pady=(0, 10))
        
        # Tool 2: Preset Notation Stamps for Instant Efficiency
        ttk.Label(control_panel, text="⭐ Quick Presets:", font=("Helvetica", 10, "bold")).pack(anchor=tk.W)
        presets_frame = ttk.Frame(control_panel)
        presets_frame.pack(fill=tk.X, pady=(0, 15))
        
        presets = ["APPROVED", "REVIEW REQUIRED", "DRAFT", "INTERNAL USE ONLY"]
        for p in presets:
            btn = ttk.Button(presets_frame, text=p, command=lambda text=p: self.insert_preset(text))
            btn.pack(fill=tk.X, pady=2)

        text_style = ttk.LabelFrame(control_panel, text="Text Style", padding=8)
        text_style.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(text_style, text="Font").grid(row=0, column=0, sticky=tk.W, padx=(0, 6), pady=3)
        self.font_combo = ttk.Combobox(
            text_style, textvariable=self.text_font_var, state="readonly", width=16,
            values=("Helvetica", "Helvetica Bold", "Times", "Times Bold", "Courier", "Courier Bold")
        )
        self.font_combo.grid(row=0, column=1, sticky=tk.EW, pady=3)
        ttk.Label(text_style, text="Size").grid(row=1, column=0, sticky=tk.W, padx=(0, 6), pady=3)
        ttk.Spinbox(
            text_style, from_=6, to=72, increment=1, textvariable=self.text_size_var, width=6
        ).grid(row=1, column=1, sticky=tk.W, pady=3)
        self.color_swatch = tk.Canvas(text_style, width=22, height=18, highlightthickness=1)
        self.color_swatch.grid(row=2, column=0, padx=(0, 6), pady=3)
        self.color_swatch.create_rectangle(1, 1, 21, 17, fill=self.text_color, outline="")
        ttk.Button(text_style, text="Choose Color", command=self.choose_text_color).grid(
            row=2, column=1, sticky=tk.W, pady=3
        )
        text_style.columnconfigure(1, weight=1)

        # Tool 3: Text Alignment & Styling Adjusters
        ttk.Label(control_panel, text="⚙️ Text Placement Positioning:", font=("Helvetica", 10, "bold")).pack(anchor=tk.W, pady=(5, 5))
        
        self.placement_var = tk.StringVar(value="top_right")
        positions = [
            ("Top Left Margin", "top_left"),
            ("Top Right Margin", "top_right"),
            ("Bottom Left Margin", "bottom_left"),
            ("Bottom Right Margin", "bottom_right")
        ]
        for text, mode in positions:
            ttk.Radiobutton(
                control_panel, text=text, variable=self.placement_var, value=mode,
                command=self.select_positioned_text
            ).pack(anchor=tk.W, pady=1)
        ttk.Button(
            control_panel, text="Custom Box", command=self.select_custom_text_box
        ).pack(anchor=tk.W, pady=(5, 0))

        # Apply Actions
        self.apply_btn = ttk.Button(control_panel, text="⚡ Apply Text to Current Page", style="Action.TButton", command=self.apply_notation, state=tk.DISABLED)
        self.apply_btn.pack(fill=tk.X, pady=(20, 5))

        ttk.Separator(control_panel).pack(fill=tk.X, pady=12)
        ttk.Label(control_panel, text="Page Editing", font=("Helvetica", 11, "bold")).pack(anchor=tk.W, pady=(0, 5))
        ttk.Radiobutton(
            control_panel, text="Erase Area", variable=self.edit_mode,
            value="erase", command=self.change_edit_mode
        ).pack(anchor=tk.W)
        ttk.Radiobutton(
            control_panel, text="Move Block", variable=self.edit_mode,
            value="move", command=self.change_edit_mode
        ).pack(anchor=tk.W)
        ttk.Radiobutton(
            control_panel, text="Text Box", variable=self.edit_mode,
            value="text", command=self.change_edit_mode
        ).pack(anchor=tk.W)
        ttk.Button(
            control_panel, text="Delete Current Page", command=self.delete_current_page
        ).pack(fill=tk.X, pady=(8, 4))
        self.edit_status = ttk.Label(
            control_panel,
            text="Drag a rectangle on the page to erase it.",
            wraplength=270
        )
        self.edit_status.pack(fill=tk.X, pady=(2, 5))

        timeline_frame = ttk.Frame(self.root, padding=(8, 4))
        timeline_frame.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(timeline_frame, text="PAGE TIMELINE", font=("Helvetica", 9, "bold")).pack(anchor=tk.W)
        drop_text = "Drop PDF files here to insert after the selected page" if DND_FILES else "Use Insert PDF Pages to add pages after the selected page"
        self.drop_area = tk.Label(
            timeline_frame, text=drop_text, bg="#eaf4f6", fg="#24515d",
            relief=tk.GROOVE, bd=1, padx=8, pady=6
        )
        self.drop_area.pack(fill=tk.X, pady=(3, 5))
        if DND_FILES:
            self.drop_area.drop_target_register(DND_FILES)
            self.drop_area.dnd_bind("<<Drop>>", self.on_pdf_drop)
        self.timeline_canvas = tk.Canvas(timeline_frame, height=112, bg="#e6e6e6", highlightthickness=0)
        self.timeline_scroll = ttk.Scrollbar(
            timeline_frame, orient=tk.HORIZONTAL, command=self.timeline_canvas.xview
        )
        self.timeline_canvas.configure(xscrollcommand=self.timeline_scroll.set)
        self.timeline_canvas.pack(fill=tk.X, expand=True)
        self.timeline_scroll.pack(fill=tk.X)
        self.timeline_canvas.bind("<ButtonPress-1>", self.on_timeline_press)
        self.timeline_canvas.bind("<B1-Motion>", self.on_timeline_drag)
        self.timeline_canvas.bind("<ButtonRelease-1>", self.on_timeline_release)

    def bind_shortcuts(self):
        # Keyboard navigation bounds for speed formatting
        self.root.bind("<Left>", lambda _event: self.prev_page())
        self.root.bind("<Right>", lambda _event: self.next_page())

    def _bind_control_mousewheel(self, _event=None):
        self.root.bind_all("<MouseWheel>", self._on_control_mousewheel)
        self.root.bind_all("<Button-4>", self._on_control_mousewheel)
        self.root.bind_all("<Button-5>", self._on_control_mousewheel)

    def _unbind_control_mousewheel(self, _event=None):
        self.root.unbind_all("<MouseWheel>")
        self.root.unbind_all("<Button-4>")
        self.root.unbind_all("<Button-5>")

    def _on_control_mousewheel(self, event):
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            delta = -int(event.delta / 120)
        self.control_canvas.yview_scroll(delta, "units")
        return "break"

    def select_custom_text_box(self):
        self.edit_mode.set("text")
        self.change_edit_mode()

    def open_pdf(self):
        file_path = filedialog.askopenfilename(filetypes=[("PDF Files", "*.pdf")])
        if file_path:
            if self.doc and self.has_unsaved_changes:
                if not self.confirm_replace_document():
                    return
            if self.doc:
                self.doc.close()
            self.remove_temp_copy()
            self.doc = fitz.open(file_path)
            self.current_page_idx = 0
            self.history.clear()
            self.redo_history.clear()
            self.has_unsaved_changes = False
            self.save_btn.config(state=tk.NORMAL)
            self.insert_btn.config(state=tk.NORMAL)
            self.prev_btn.config(state=tk.NORMAL)
            self.next_btn.config(state=tk.NORMAL)
            self.apply_btn.config(state=tk.NORMAL)
            self.erased_regions.clear()
            self.pending_move = None
            self.edit_status.config(text="Drag a rectangle on the page to erase it.")
            self.update_history_buttons()
            self.write_temp_copy()
            self.refresh_timeline()
            self.render_page()

    def _capture_state(self):
        return (
            self.doc.tobytes(garbage=3, deflate=True),
            self.current_page_idx,
            copy.deepcopy(self.erased_regions)
        )

    def _record_change(self):
        self.history.append(self._capture_state())
        if len(self.history) > self.history_limit:
            self.history.pop(0)
        self.redo_history.clear()
        self.update_history_buttons()

    def _restore_state(self, state):
        document_bytes, page_idx, erased_regions = state
        self.doc.close()
        self.doc = fitz.open(stream=document_bytes, filetype="pdf")
        self.current_page_idx = min(page_idx, len(self.doc) - 1)
        self.erased_regions = erased_regions
        self.pending_move = None
        self.has_unsaved_changes = True
        self.write_temp_copy()
        self.update_history_buttons()
        self.refresh_timeline()
        self.render_page()

    def _restore_failed_change(self, state):
        document_bytes, page_idx, erased_regions = state
        self.doc.close()
        self.doc = fitz.open(stream=document_bytes, filetype="pdf")
        self.current_page_idx = min(page_idx, len(self.doc) - 1)
        self.erased_regions = erased_regions
        self.update_history_buttons()
        self.refresh_timeline()
        self.render_page()

    def update_history_buttons(self):
        if not hasattr(self, "undo_btn"):
            return
        self.undo_btn.config(state=tk.NORMAL if self.history else tk.DISABLED)
        self.redo_btn.config(state=tk.NORMAL if self.redo_history else tk.DISABLED)

    def undo(self):
        if self.doc and self.history:
            self.redo_history.append(self._capture_state())
            state = self.history.pop()
            self._restore_state(state)

    def redo(self):
        if self.doc and self.redo_history:
            self.history.append(self._capture_state())
            state = self.redo_history.pop()
            self._restore_state(state)

    def toggle_temp_copy(self):
        if not self.doc:
            return
        if self.temp_copy_var.get():
            self.write_temp_copy()
        else:
            self.remove_temp_copy()

    def write_temp_copy(self):
        if not self.doc or not self.temp_copy_var.get():
            return
        try:
            if not self.temp_copy_path:
                descriptor, self.temp_copy_path = tempfile.mkstemp(
                    prefix="pdf_editor_work_", suffix=".pdf"
                )
                os.close(descriptor)
            pending_path = self.temp_copy_path + ".pending"
            with open(pending_path, "wb") as temp_file:
                temp_file.write(self.doc.tobytes(garbage=3, deflate=True))
            os.replace(pending_path, self.temp_copy_path)
        except (OSError, RuntimeError) as error:
            messagebox.showwarning("Temporary Copy", f"Could not update the temporary work copy:\n{error}")

    def remove_temp_copy(self):
        if not self.temp_copy_path:
            return
        for path in (self.temp_copy_path, self.temp_copy_path + ".pending"):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        self.temp_copy_path = None

    def mark_changed(self):
        self.has_unsaved_changes = True
        self.write_temp_copy()

    def confirm_replace_document(self):
        if self.temp_copy_path:
            prompt = (
                "Save the current document before opening another?\n\n"
                f"Choose No to discard these changes. Temporary copy:\n{self.temp_copy_path}"
            )
        else:
            prompt = "Save the current document before opening another?"
        answer = messagebox.askyesnocancel("Unsaved Changes", prompt)
        if answer is None:
            return False
        if answer:
            return self.save_pdf()
        self.remove_temp_copy()
        return True

    def on_close(self):
        if self.doc and self.has_unsaved_changes:
            if self.temp_copy_path:
                prompt = f"Save a final PDF now? Choose No to keep the temporary work copy at:\n{self.temp_copy_path}"
            else:
                prompt = "Save a final PDF before closing?"
            answer = messagebox.askyesnocancel("Unsaved Changes", prompt)
            if answer is None:
                return
            if answer and not self.save_pdf():
                return
        elif not self.has_unsaved_changes:
            self.remove_temp_copy()
        if self.doc:
            self.doc.close()
        self.root.destroy()

    def choose_pdf_to_insert(self):
        file_paths = filedialog.askopenfilenames(filetypes=[("PDF Files", "*.pdf")])
        if file_paths:
            self.insert_pdf_files(file_paths)

    def on_pdf_drop(self, event):
        self.insert_pdf_files(self.root.tk.splitlist(event.data))
        return "copy"

    def insert_pdf_files(self, file_paths):
        if not self.doc:
            messagebox.showwarning("Open a PDF First", "Open the document that should receive the inserted pages.")
            return

        sources = []
        try:
            for file_path in file_paths:
                source = fitz.open(file_path)
                if not source.is_pdf or len(source) == 0:
                    source.close()
                    raise ValueError(f"{file_path} is not a non-empty PDF.")
                sources.append((file_path, source))
        except Exception as error:
            for _, source in sources:
                source.close()
            messagebox.showerror("Unable to Insert PDF", str(error))
            return

        insert_at = self.current_page_idx + 1
        first_inserted_page = insert_at
        inserted_count = 0
        try:
            if sources:
                self._record_change()
            for _, source in sources:
                page_count = len(source)
                self.doc.insert_pdf(source, start_at=insert_at)
                shifted_regions = {}
                for page_idx, regions in self.erased_regions.items():
                    shifted_idx = page_idx + page_count if page_idx >= insert_at else page_idx
                    shifted_regions[shifted_idx] = regions
                self.erased_regions = shifted_regions
                insert_at += page_count
                inserted_count += page_count
        except Exception as error:
            messagebox.showerror("Unable to Insert PDF", str(error))
        finally:
            for _, source in sources:
                source.close()

        if inserted_count:
            self.current_page_idx = first_inserted_page
            self.pending_move = None
            self.mark_changed()
            self.refresh_timeline()
            self.render_page()
            messagebox.showinfo("Pages Inserted", f"Inserted {inserted_count} page(s) after the previously selected page.")

    def render_page(self):
        if not self.doc:
            return
        
        page = self.doc[self.current_page_idx]
        
        # Scale resolution rendering dynamically up for modern sharp displays
        mat = fitz.Matrix(self.zoom_scale, self.zoom_scale)
        pix = page.get_pixmap(matrix=mat)
        self.rendered_size = (pix.width, pix.height)
        
        # Convert raw binary pixmap to Tkinter compatible PhotoImage
        img_data = pix.tobytes("ppm")
        img = Image.open(io.BytesIO(img_data))
        self.tk_img = ImageTk.PhotoImage(img)
        
        # Refresh drawing canvas bounds
        self.canvas.delete("all")
        self.canvas.create_image(20, 20, anchor=tk.NW, image=self.tk_img)
        self.canvas.config(scrollregion=(0, 0, pix.width + 40, pix.height + 40))
        self.draw_erased_regions(page)
        self.update_timeline_selection()
        
        # Update top count labels
        self.page_label.config(text=f"Page: {self.current_page_idx + 1} / {len(self.doc)}")

    def refresh_timeline(self):
        self.timeline_canvas.delete("all")
        self.timeline_items.clear()
        self.timeline_canvas.image = []
        if not self.doc:
            return

        card_width = 92
        for page_idx, page in enumerate(self.doc):
            x = 6 + page_idx * card_width
            pix = page.get_pixmap(matrix=fitz.Matrix(0.14, 0.14), alpha=False)
            image = Image.open(io.BytesIO(pix.tobytes("ppm")))
            image.thumbnail((68, 78))
            thumbnail = ImageTk.PhotoImage(image)
            self.timeline_canvas.create_image(x + 10, 5, anchor=tk.NW, image=thumbnail)
            self.timeline_canvas.image.append(thumbnail)
            self.timeline_canvas.create_text(x + 44, 94, text=str(page_idx + 1), font=("Helvetica", 9))

            page_rect = page.rect
            for region in self.erased_regions.get(page_idx, []):
                points = [
                    fitz.Point(region.x0, region.y0) * page.rotation_matrix,
                    fitz.Point(region.x1, region.y1) * page.rotation_matrix
                ]
                left = x + 10 + min(point.x for point in points) / page_rect.width * image.width
                top = 5 + min(point.y for point in points) / page_rect.height * image.height
                right = x + 10 + max(point.x for point in points) / page_rect.width * image.width
                bottom = 5 + max(point.y for point in points) / page_rect.height * image.height
                self.timeline_canvas.create_rectangle(
                    left, top, right, bottom, fill="#e35d5b", stipple="gray50", outline=""
                )

            outline = self.timeline_canvas.create_rectangle(
                x + 5, 1, x + 83, 108, outline="#1687a7", width=3 if page_idx == self.current_page_idx else 1
            )
            self.timeline_items[page_idx] = outline

        self.timeline_canvas.configure(scrollregion=(0, 0, max(100, 6 + len(self.doc) * card_width), 112))

    def on_timeline_press(self, event):
        if not self.doc:
            return
        x = self.timeline_canvas.canvasx(event.x)
        page_idx = int((x - 6) // 92)
        if 0 <= page_idx < len(self.doc):
            self.timeline_drag_source = page_idx
            self.timeline_drag_start_x = x
            self.timeline_drag_moved = False

    def on_timeline_drag(self, event):
        if self.timeline_drag_source is None or not self.doc:
            return
        x = self.timeline_canvas.canvasx(event.x)
        if abs(x - self.timeline_drag_start_x) < 6:
            return
        self.timeline_drag_moved = True
        slot = max(0, min(len(self.doc), round((x - 6) / 92)))
        marker_x = 6 + slot * 92
        if self.timeline_drag_marker is None:
            self.timeline_drag_marker = self.timeline_canvas.create_line(
                marker_x, 0, marker_x, 110, fill="#d44b43", width=3, tags="drag-marker"
            )
        else:
            self.timeline_canvas.coords(self.timeline_drag_marker, marker_x, 0, marker_x, 110)
        self.timeline_canvas.tag_raise(self.timeline_drag_marker)

    def on_timeline_release(self, event):
        source_idx = self.timeline_drag_source
        did_drag = self.timeline_drag_moved
        self.timeline_drag_source = None
        self.timeline_drag_start_x = None
        self.timeline_drag_moved = False
        if self.timeline_drag_marker is not None:
            self.timeline_canvas.delete(self.timeline_drag_marker)
            self.timeline_drag_marker = None
        if source_idx is None or not self.doc:
            return

        if not did_drag:
            self.go_to_page(source_idx)
            return

        x = self.timeline_canvas.canvasx(event.x)
        slot = max(0, min(len(self.doc), int((x - 6 + 46) // 92)))
        order = list(range(len(self.doc)))
        moved_page = order.pop(source_idx)
        target_idx = max(0, min(len(order), slot - (1 if slot > source_idx else 0)))
        order.insert(target_idx, moved_page)
        if order == list(range(len(self.doc))):
            self.go_to_page(source_idx)
            return

        self._record_change()
        self.doc.select(order)
        self.erased_regions = {
            new_idx: self.erased_regions[old_idx]
            for new_idx, old_idx in enumerate(order)
            if old_idx in self.erased_regions
        }
        self.current_page_idx = target_idx
        self.pending_move = None
        self.mark_changed()
        self.refresh_timeline()
        self.render_page()

    def update_timeline_selection(self):
        if not hasattr(self, "timeline_canvas"):
            return
        for page_idx, item in self.timeline_items.items():
            self.timeline_canvas.itemconfigure(
                item, width=3 if page_idx == self.current_page_idx else 1
            )

    def go_to_page(self, page_idx):
        if self.doc and 0 <= page_idx < len(self.doc):
            self.current_page_idx = page_idx
            self.pending_move = None
            self.render_page()

    def _canvas_point_to_page(self, x, y):
        page = self.doc[self.current_page_idx]
        width, height = self.rendered_size
        display_point = fitz.Point(
            (x - 20) * page.rect.width / width,
            (y - 20) * page.rect.height / height
        )
        point = display_point * page.derotation_matrix
        return fitz.Point(
            min(max(point.x, page.rect.x0), page.rect.x1),
            min(max(point.y, page.rect.y0), page.rect.y1)
        )

    def _page_rect_to_canvas(self, rect, page):
        points = [
            fitz.Point(rect.x0, rect.y0) * page.rotation_matrix,
            fitz.Point(rect.x1, rect.y1) * page.rotation_matrix
        ]
        width, height = self.rendered_size
        x_scale = width / page.rect.width
        y_scale = height / page.rect.height
        return (
            20 + min(point.x for point in points) * x_scale,
            20 + min(point.y for point in points) * y_scale,
            20 + max(point.x for point in points) * x_scale,
            20 + max(point.y for point in points) * y_scale
        )

    def draw_erased_regions(self, page):
        for region in self.erased_regions.get(self.current_page_idx, []):
            self.canvas.create_rectangle(
                *self._page_rect_to_canvas(region, page),
                fill="#e35d5b", stipple="gray50", outline="#b72f35", width=2,
                tags="erased-region"
            )
        if self.text_box_rect and self.text_box_page_idx == self.current_page_idx:
            self.canvas.create_rectangle(
                *self._page_rect_to_canvas(self.text_box_rect, page),
                fill="", outline="#1687a7", width=2, dash=(5, 3), tags="text-box-selection"
            )

    def choose_text_color(self):
        _, color = colorchooser.askcolor(color=self.text_color, title="Text Color")
        if color:
            self.text_color = color
            self.color_swatch.itemconfigure(1, fill=color)

    def change_edit_mode(self):
        self.pending_move = None
        if self.edit_mode.get() == "erase":
            self.edit_status.config(text="Drag a rectangle over the content to erase it.")
        elif self.edit_mode.get() == "move":
            self.edit_status.config(text="Drag to select a block, then drag again to place it.")
        elif self.edit_mode.get() == "stamp":
            self.edit_status.config(text="Choose a text placement, enter text, then apply it to the page.")
        else:
            self.edit_status.config(text="Drag a box on the page, enter text, then apply it inside the box.")

    def select_positioned_text(self):
        self.edit_mode.set("stamp")
        self.text_box_rect = None
        self.text_box_page_idx = None
        self.change_edit_mode()
        if self.doc:
            self.render_page()

    def begin_canvas_action(self, event):
        if not self.doc:
            return
        if self.edit_mode.get() == "stamp":
            return
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        point = self._canvas_point_to_page(x, y)

        if self.edit_mode.get() == "move" and self.pending_move:
            self.drag_start = fitz.Point(x, y)
            self.drag_start_page = point
            self.selection_item = self.canvas.create_rectangle(
                x, y, x + 1, y + 1, outline="#1687a7", width=2, dash=(4, 2)
            )
            return

        self.pending_move = None
        self.drag_start = fitz.Point(x, y)
        self.drag_start_page = point
        outline = {"erase": "#e35d5b", "move": "#1687a7", "text": "#24a16c"}[self.edit_mode.get()]
        self.selection_item = self.canvas.create_rectangle(
            x, y, x + 1, y + 1,
            outline=outline,
            width=2, dash=(4, 2)
        )

    def update_canvas_action(self, event):
        if self.drag_start is None or self.selection_item is None:
            return
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        if self.edit_mode.get() == "move" and self.pending_move:
            source = self.pending_move["rect"]
            page = self.doc[self.current_page_idx]
            width, height = self.rendered_size
            box_width = source.width * width / page.rect.width
            box_height = source.height * height / page.rect.height
            self.canvas.coords(self.selection_item, x, y, x + box_width, y + box_height)
        else:
            self.canvas.coords(self.selection_item, self.drag_start.x, self.drag_start.y, x, y)

    def finish_canvas_action(self, event):
        if self.drag_start is None:
            return
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        page = self.doc[self.current_page_idx]

        if self.edit_mode.get() == "text":
            end_point = self._canvas_point_to_page(x, y)
            rect = fitz.Rect(self.drag_start_page, end_point)
            if rect.width >= 2 and rect.height >= 2:
                self.text_box_rect = rect
                self.text_box_page_idx = self.current_page_idx
                self.edit_status.config(text="Text box selected. Enter text and choose Apply Text to Current Page.")
                self.render_page()
        elif self.edit_mode.get() == "move" and self.pending_move:
            destination = self._canvas_point_to_page(x, y)
            self.place_pending_move(destination)
        else:
            end_point = self._canvas_point_to_page(x, y)
            rect = fitz.Rect(self.drag_start_page, end_point)
            if rect.width >= 2 and rect.height >= 2:
                if self.edit_mode.get() == "erase":
                    self._record_change()
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                    page.apply_redactions()
                    self.erased_regions.setdefault(self.current_page_idx, []).append(rect)
                    self.mark_changed()
                    self.refresh_timeline()
                    self.render_page()
                else:
                    pix = page.get_pixmap(
                        matrix=fitz.Matrix(self.zoom_scale, self.zoom_scale), clip=rect, alpha=True
                    )
                    self.pending_move = {"rect": rect, "image": pix.tobytes("png")}
                    self.edit_status.config(text="Block selected. Drag on the page to choose its new top-left position.")

        if self.selection_item is not None:
            self.canvas.delete(self.selection_item)
        self.selection_item = None
        self.drag_start = None
        self.drag_start_page = None

    def place_pending_move(self, destination):
        page = self.doc[self.current_page_idx]
        source = self.pending_move["rect"]
        width = min(source.width, page.rect.width)
        height = min(source.height, page.rect.height)
        x0 = min(max(destination.x, page.rect.x0), page.rect.x1 - width)
        y0 = min(max(destination.y, page.rect.y0), page.rect.y1 - height)
        target = fitz.Rect(x0, y0, x0 + width, y0 + height)

        self._record_change()
        page.add_redact_annot(source, fill=(1, 1, 1))
        page.apply_redactions()
        page.insert_image(target, stream=self.pending_move["image"])
        self.erased_regions.setdefault(self.current_page_idx, []).append(source)
        self.pending_move = None
        self.mark_changed()
        self.edit_status.config(text="Block moved. Its original area is marked in red.")
        self.refresh_timeline()
        self.render_page()

    def delete_current_page(self):
        if not self.doc:
            return
        if len(self.doc) <= 1:
            messagebox.showwarning("Cannot Delete Page", "A PDF must keep at least one page.")
            return
        if not messagebox.askyesno(
            "Delete Page", f"Delete page {self.current_page_idx + 1} from this document?"
        ):
            return

        deleted_idx = self.current_page_idx
        self._record_change()
        self.doc.delete_page(deleted_idx)
        updated_regions = {}
        for page_idx, regions in self.erased_regions.items():
            if page_idx < deleted_idx:
                updated_regions[page_idx] = regions
            elif page_idx > deleted_idx:
                updated_regions[page_idx - 1] = regions
        self.erased_regions = updated_regions
        self.current_page_idx = min(deleted_idx, len(self.doc) - 1)
        self.pending_move = None
        self.mark_changed()
        self.refresh_timeline()
        self.render_page()

    def insert_preset(self, text):
        self.notation_box.delete("1.0", tk.END)
        self.notation_box.insert("1.0", text)

    def _selected_font_name(self):
        return {
            "Helvetica": "helv",
            "Helvetica Bold": "hebo",
            "Times": "tiro",
            "Times Bold": "tibo",
            "Courier": "cour",
            "Courier Bold": "cobo"
        }[self.text_font_var.get()]

    def apply_notation(self):
        if not self.doc:
            return
        
        text_to_add = self.notation_box.get("1.0", tk.END).strip()
        if not text_to_add:
            messagebox.showwarning("Empty Notation", "Please write or select notation text first.")
            return

        if self.edit_mode.get() == "text" and (
            self.text_box_rect is None or self.text_box_page_idx != self.current_page_idx
        ):
            messagebox.showwarning("Select a Text Box", "Drag a text box on the current page first.")
            return

        try:
            font_size = int(self.text_size_var.get())
        except (ValueError, tk.TclError):
            messagebox.showwarning("Invalid Font Size", "Enter a font size between 6 and 72 points.")
            return
        if not 6 <= font_size <= 72:
            messagebox.showwarning("Invalid Font Size", "Enter a font size between 6 and 72 points.")
            return

        page = self.doc[self.current_page_idx]
        color = tuple(int(self.text_color[index:index + 2], 16) / 255 for index in (1, 3, 5))
        font_name = self._selected_font_name()
        checkpoint = self._capture_state()
        self._record_change()
        try:
            if self.edit_mode.get() == "text":
                remaining_space = page.insert_textbox(
                    self.text_box_rect,
                    text_to_add,
                    fontname=font_name,
                    fontsize=font_size,
                    color=color,
                    align=0
                )
                if remaining_space < 0:
                    self.history.pop()
                    self._restore_failed_change(checkpoint)
                    messagebox.showwarning(
                        "Text Does Not Fit",
                        "The text is too large for the selected box. Reduce the font size or select a larger box."
                    )
                    return
            else:
                page_rect = page.rect
                margin = 35
                pos_mode = self.placement_var.get()
                if pos_mode == "top_left":
                    point = fitz.Point(margin, margin + font_size)
                elif pos_mode == "top_right":
                    point = fitz.Point(max(margin, page_rect.width - 220), margin + font_size)
                elif pos_mode == "bottom_left":
                    point = fitz.Point(margin, page_rect.height - margin)
                else:
                    point = fitz.Point(max(margin, page_rect.width - 220), page_rect.height - margin)
                page.insert_text(
                    point, text_to_add, fontsize=font_size, color=color, fontname=font_name
                )
        except Exception as error:
            self.history.pop()
            self._restore_failed_change(checkpoint)
            messagebox.showerror("Text Could Not Be Applied", str(error))
            return
        
        # Clear notation frame and update render visually
        self.notation_box.delete("1.0", tk.END)
        self.text_box_rect = None
        self.text_box_page_idx = None
        self.mark_changed()
        self.render_page()
        messagebox.showinfo("Applied", "Notation stamped onto document coordinate stack successfully!")

    def next_page(self):
        if self.doc and self.current_page_idx < len(self.doc) - 1:
            self.current_page_idx += 1
            self.render_page()

    def prev_page(self):
        if self.doc and self.current_page_idx > 0:
            self.current_page_idx -= 1
            self.render_page()

    def save_pdf(self):
        if not self.doc:
            return False
        save_path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF Files", "*.pdf")])
        if not save_path:
            return False
        try:
            pdf_bytes = self.doc.tobytes(garbage=3, deflate=True)
            with open(save_path, "wb") as output_file:
                output_file.write(pdf_bytes)
        except (OSError, RuntimeError) as error:
            messagebox.showerror("Save Failed", str(error))
            return False
        self.has_unsaved_changes = False
        self.history.clear()
        self.redo_history.clear()
        self.update_history_buttons()
        self.remove_temp_copy()
        messagebox.showinfo("Saved", f"Edited file safely exported to:\n{save_path}")
        return True


if __name__ == "__main__":
    root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    app = SimplePDFEditor(root)
    root.mainloop()