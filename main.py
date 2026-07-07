"""
Convertisseur Markdown → DOCX
Utilise Pandoc via pypandoc pour la conversion.
Un template .dotx peut être appliqué pour la mise en page automatique.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import filedialog, messagebox, scrolledtext, ttk


# ---------------------------------------------------------------------------
# Configuration Pandoc (mode PyInstaller --onefile)
# ---------------------------------------------------------------------------

def _configure_pandoc():
    """
    Quand l'app est empaquetée (PyInstaller --onefile), le binaire pandoc
    est extrait dans sys._MEIPASS. On l'indique à pypandoc via l'env var.
    """
    if getattr(sys, "frozen", False):
        pandoc_exe = os.path.join(getattr(sys, "_MEIPASS", ""), "pandoc.exe")
        if os.path.exists(pandoc_exe):
            os.environ["PYPANDOC_PANDOC"] = pandoc_exe


def _check_pandoc():
    """Retourne True si pypandoc et pandoc sont disponibles."""
    try:
        import pypandoc
        pypandoc.get_pandoc_version()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Rendu des diagrammes Mermaid
# ---------------------------------------------------------------------------

_MERMAID_RE = re.compile(r'```mermaid[ \t]*\r?\n(.*?)\r?\n```', re.DOTALL | re.IGNORECASE)


def _render_mermaid_mmdc(code: str, out_png: str) -> bool:
    """
    Tente le rendu via mmdc (mermaid-cli, nécessite Node.js).
    Essaie d'abord 'mmdc' directement, puis 'npx mmdc'.
    """
    for cmd_prefix in (['mmdc'], ['npx', 'mmdc']):
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.mmd', delete=False, encoding='utf-8'
            ) as f:
                f.write(code)
                mmd = f.name
            try:
                result = subprocess.run(
                    cmd_prefix + ['-i', mmd, '-o', out_png, '-b', 'transparent'],
                    capture_output=True,
                    timeout=30,
                )
                if result.returncode == 0 and os.path.isfile(out_png):
                    return True
            finally:
                try:
                    os.unlink(mmd)
                except OSError:
                    pass
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    return False


def _render_mermaid_ink(code: str, out_png: str) -> bool:
    """
    Tente le rendu via l'API mermaid.ink (nécessite une connexion internet).
    """
    try:
        payload = json.dumps({"code": code, "mermaid": {"theme": "default"}})
        b64 = base64.urlsafe_b64encode(payload.encode('utf-8')).decode('ascii')
        url = f"https://mermaid.ink/img/{b64}"
        req = urllib.request.Request(url, headers={"User-Agent": "md2docx/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        # Un fichier PNG valide fait au moins quelques centaines d'octets
        if len(data) < 200:
            return False
        with open(out_png, 'wb') as f:
            f.write(data)
        return True
    except Exception:
        return False


def preprocess_mermaid(md_path: str, log_fn=None):
    """
    Parcourt le Markdown, convertit chaque bloc ```mermaid en PNG,
    remplace le bloc par une référence image.

    Retourne (chemin_md_modifié, répertoire_temp | None).
    Si aucun bloc mermaid n'est trouvé, retourne (md_path, None).
    """
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if not _MERMAID_RE.search(content):
        return md_path, None

    tmp_dir = tempfile.mkdtemp(prefix='md2docx_')
    counter = {'idx': 0, 'ok': 0, 'fail': 0}

    def replace_block(m):
        idx = counter['idx']
        counter['idx'] += 1
        code = m.group(1).strip()
        out_png = os.path.join(tmp_dir, f'mermaid_{idx}.png')

        if _render_mermaid_mmdc(code, out_png):
            method = 'mmdc (local)'
        elif _render_mermaid_ink(code, out_png):
            method = 'mermaid.ink (en ligne)'
        else:
            method = None

        if method:
            counter['ok'] += 1
            if log_fn:
                log_fn(f"  Mermaid #{idx + 1} → rendu via {method}")
            img_path = out_png.replace('\\', '/')
            return f'![Diagramme {idx + 1}]({img_path})'
        else:
            counter['fail'] += 1
            if log_fn:
                log_fn(
                    f"  ⚠ Mermaid #{idx + 1} : échec (mmdc absent et mermaid.ink inaccessible)"
                )
            return m.group(0)  # conserve le bloc original

    new_content = _MERMAID_RE.sub(replace_block, content)

    if log_fn:
        log_fn(
            f"Mermaid : {counter['ok']} rendu(s) OK, {counter['fail']} échec(s)"
        )

    tmp_md = os.path.join(tmp_dir, 'input.md')
    with open(tmp_md, 'w', encoding='utf-8') as f:
        f.write(new_content)

    return tmp_md, tmp_dir


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Convertisseur Markdown → DOCX")
        self.resizable(True, True)
        self.minsize(580, 420)

        self._md_path = tk.StringVar()
        self._dotx_path = tk.StringVar()
        self._out_path = tk.StringVar()

        self._build_ui()
        self._center_window(640, 500)

    # ------------------------------------------------------------------ #
    #  Interface                                                           #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        try:
            ttk.Style(self).theme_use("vista")
        except tk.TclError:
            pass

        outer = ttk.Frame(self, padding=16)
        outer.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)

        row = 0

        # Titre
        ttk.Label(
            outer,
            text="Convertisseur Markdown → DOCX",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=row, column=0, columnspan=3, pady=(0, 18), sticky="w")

        # -- Fichier Markdown ----------------------------------------------
        row += 1
        ttk.Label(outer, text="Fichier Markdown (.md) :").grid(
            row=row, column=0, columnspan=3, sticky="w"
        )
        row += 1
        ttk.Entry(outer, textvariable=self._md_path).grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=(0, 6)
        )
        ttk.Button(outer, text="Parcourir…", command=self._browse_md).grid(
            row=row, column=2, sticky="ew"
        )

        # -- Template .dotx (optionnel) ------------------------------------
        row += 1
        ttk.Label(
            outer,
            text="Template Word (.dotx / .docx)  —  optionnel :",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 0))
        row += 1
        ttk.Entry(outer, textvariable=self._dotx_path).grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=(0, 6)
        )
        ttk.Button(outer, text="Parcourir…", command=self._browse_dotx).grid(
            row=row, column=2, sticky="ew"
        )

        # -- Fichier de sortie ---------------------------------------------
        row += 1
        ttk.Label(outer, text="Fichier de sortie (.docx) :").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(10, 0)
        )
        row += 1
        ttk.Entry(outer, textvariable=self._out_path).grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=(0, 6)
        )
        ttk.Button(
            outer, text="Enregistrer sous…", command=self._browse_out
        ).grid(row=row, column=2, sticky="ew")

        # -- Bouton Convertir ----------------------------------------------
        row += 1
        self._btn = ttk.Button(
            outer, text="   Convertir   ", command=self._start_conversion
        )
        self._btn.grid(row=row, column=0, columnspan=3, pady=14)

        # -- Barre de progression ------------------------------------------
        row += 1
        self._progress = ttk.Progressbar(outer, mode="indeterminate", length=400)
        self._progress.grid(row=row, column=0, columnspan=3, sticky="ew")

        # -- Journal -------------------------------------------------------
        row += 1
        ttk.Label(outer, text="Journal :").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(8, 2)
        )
        row += 1
        self._log = scrolledtext.ScrolledText(
            outer, height=7, state="disabled", font=("Consolas", 9), wrap="word"
        )
        self._log.grid(row=row, column=0, columnspan=3, sticky="nsew")
        outer.rowconfigure(row, weight=1)

    # ------------------------------------------------------------------ #
    #  Sélecteurs de fichiers                                              #
    # ------------------------------------------------------------------ #

    def _browse_md(self):
        path = filedialog.askopenfilename(
            title="Sélectionner un fichier Markdown",
            filetypes=[
                ("Markdown", "*.md *.markdown"),
                ("Tous les fichiers", "*.*"),
            ],
        )
        if path:
            self._md_path.set(path)
            if not self._out_path.get():
                self._out_path.set(os.path.splitext(path)[0] + ".docx")

    def _browse_dotx(self):
        path = filedialog.askopenfilename(
            title="Sélectionner un template Word",
            filetypes=[
                ("Templates Word", "*.dotx *.docx"),
                ("Tous les fichiers", "*.*"),
            ],
        )
        if path:
            self._dotx_path.set(path)

    def _browse_out(self):
        path = filedialog.asksaveasfilename(
            title="Enregistrer le fichier DOCX",
            defaultextension=".docx",
            filetypes=[
                ("Document Word", "*.docx"),
                ("Tous les fichiers", "*.*"),
            ],
        )
        if path:
            self._out_path.set(path)

    # ------------------------------------------------------------------ #
    #  Conversion                                                          #
    # ------------------------------------------------------------------ #

    def _start_conversion(self):
        md = self._md_path.get().strip()
        out = self._out_path.get().strip()
        dotx = self._dotx_path.get().strip() or None

        if not md:
            messagebox.showwarning("Champ requis", "Veuillez sélectionner un fichier Markdown.")
            return
        if not os.path.isfile(md):
            messagebox.showerror("Fichier introuvable", f"Fichier Markdown introuvable :\n{md}")
            return
        if not out:
            messagebox.showwarning("Champ requis", "Veuillez spécifier le fichier de sortie.")
            return
        if dotx and not os.path.isfile(dotx):
            messagebox.showerror("Fichier introuvable", f"Template introuvable :\n{dotx}")
            return

        self._btn.state(["disabled"])
        self._progress.start(12)
        threading.Thread(
            target=self._do_convert, args=(md, out, dotx), daemon=True
        ).start()

    def _do_convert(self, md, out, dotx):
        tmp_dir = None
        try:
            import pypandoc

            self._log_write(f"Source   : {md}")
            if dotx:
                self._log_write(f"Template : {dotx}")
            self._log_write(f"Sortie   : {out}")

            # -- Pré-traitement des diagrammes Mermaid ---------------------
            self._log_write("Recherche de diagrammes Mermaid…")
            md_to_use, tmp_dir = preprocess_mermaid(md, self._log_write)

            # -- Conversion Pandoc -----------------------------------------
            self._log_write("Conversion Pandoc en cours…")
            extra_args = ["--standalone"]
            if dotx:
                extra_args += ["--reference-doc", dotx]

            pypandoc.convert_file(md_to_use, "docx", outputfile=out, extra_args=extra_args)

            self._log_write("✓ Conversion réussie !")
            self.after(
                0,
                lambda: messagebox.showinfo(
                    "Succès", f"Fichier créé avec succès :\n\n{out}"
                ),
            )
        except Exception as exc:
            msg = str(exc)
            self._log_write(f"✗ Erreur : {msg}")
            self.after(0, lambda m=msg: messagebox.showerror("Erreur de conversion", m))
        finally:
            self.after(0, self._on_done)
            if tmp_dir and os.path.isdir(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def _on_done(self):
        self._progress.stop()
        self._btn.state(["!disabled"])

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _log_write(self, text):
        def _do():
            self._log.configure(state="normal")
            self._log.insert(tk.END, text + "\n")
            self._log.see(tk.END)
            self._log.configure(state="disabled")

        self.after(0, _do)

    def _center_window(self, w, h):
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _configure_pandoc()

    if not _check_pandoc():
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Dépendance manquante",
            "Pandoc ou pypandoc n'est pas disponible.\n\n"
            "1. Installez pypandoc :\n"
            "   pip install pypandoc\n\n"
            "2. Installez Pandoc :\n"
            "   https://pandoc.org/installing.html",
        )
        sys.exit(1)

    App().mainloop()
