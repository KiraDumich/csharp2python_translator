import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from translator import Translator, TranslationResult

EXAMPLE_CODE = """class Calculator {
    int count;

    int Add(int a, int b) {
        int result;
        result = a + b;
        return result;
    }

    void Test() {
        int x = 5;
        if (x > 0) {
            x = x * 2;
        }
    }
}
"""

CODE_FONT = ("Consolas", 11)


class TranslatorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.translator = Translator()

        root.title("Транслятор C# → Python")
        root.geometry("1200x760")
        root.minsize(800, 500)

        self.build_toolbar()
        self.build_editors()
        self.build_details()

        self.status = tk.StringVar(value="Вставьте код на C# или откройте файл и нажмите «Транслировать»")
        ttk.Label(root, textvariable=self.status, anchor="w", padding=(8, 3)).pack(fill="x", side="bottom")

        root.bind("<F5>", lambda event: self.translate())

        self.source_text.insert("1.0", EXAMPLE_CODE)

    def build_toolbar(self):
        toolbar = ttk.Frame(self.root, padding=(8, 6))
        toolbar.pack(fill="x", side="top")

        ttk.Button(toolbar, text="Открыть файл…", command=self.open_file).pack(side="left")
        ttk.Button(toolbar, text="Транслировать (F5)", command=self.translate).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Сохранить результат…", command=self.save_result).pack(side="left")
        ttk.Button(toolbar, text="Очистить", command=self.clear).pack(side="left", padx=6)

    def build_editors(self):
        self.panes = ttk.PanedWindow(self.root, orient="vertical")
        self.panes.pack(fill="both", expand=True, padx=8)

        editors = ttk.PanedWindow(self.panes, orient="horizontal")
        self.panes.add(editors, weight=3)

        source_frame = ttk.LabelFrame(editors, text="Исходный код (C#)")
        self.source_text = self.create_text(source_frame)
        editors.add(source_frame, weight=1)

        result_frame = ttk.LabelFrame(editors, text="Результат (Python)")
        self.result_text = self.create_text(result_frame, readonly=True)
        editors.add(result_frame, weight=1)

    def build_details(self):
        notebook = ttk.Notebook(self.panes)
        self.panes.add(notebook, weight=2)
        self.notebook = notebook

        self.detail_texts = {}
        for title in ("Сообщения", "Токены", "AST", "Таблица символов"):
            frame = ttk.Frame(notebook)
            self.detail_texts[title] = self.create_text(frame, readonly=True)
            notebook.add(frame, text=title)

        messages = self.detail_texts["Сообщения"]
        messages.tag_configure("error", foreground="#c62828")
        messages.tag_configure("warning", foreground="#b26a00")
        messages.tag_configure("success", foreground="#2e7d32")

    def create_text(self, parent, readonly: bool = False) -> tk.Text:
        text = tk.Text(parent, font=CODE_FONT, wrap="none", undo=not readonly)
        scroll_y = ttk.Scrollbar(parent, orient="vertical", command=text.yview)
        scroll_x = ttk.Scrollbar(parent, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        scroll_y.pack(side="right", fill="y")
        scroll_x.pack(side="bottom", fill="x")
        text.pack(side="left", fill="both", expand=True)

        if readonly:
            text.configure(state="disabled")
        return text

    def set_text(self, text: tk.Text, content: str):
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("1.0", content)
        text.configure(state="disabled")

    # Действия

    def translate(self):
        code = self.source_text.get("1.0", "end-1c")
        if not code.strip():
            self.status.set("Нет исходного кода для трансляции")
            return

        try:
            result = self.translator.translate(code)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Внутренняя ошибка транслятора: {e}")
            return

        self.set_text(self.result_text, result.python_code)
        self.show_messages(result)
        self.set_text(self.detail_texts["Токены"], self.format_tokens(result))
        self.set_text(self.detail_texts["AST"], repr(result.ast) if result.ast else "")
        self.set_text(self.detail_texts["Таблица символов"], self.format_symbols(result))

        if result.success:
            self.status.set(f"Трансляция выполнена. Предупреждений: {len(result.warnings)}")
        else:
            self.status.set(f"Трансляция не выполнена. Ошибок: {len(result.errors)}, "
                            f"предупреждений: {len(result.warnings)}")
            self.notebook.select(0)

    def show_messages(self, result: TranslationResult):
        messages = self.detail_texts["Сообщения"]
        messages.configure(state="normal")
        messages.delete("1.0", "end")

        for error in result.errors:
            messages.insert("end", error + "\n", "error")
        for warning in result.warnings:
            messages.insert("end", warning + "\n", "warning")
        if result.success:
            messages.insert("end", "Трансляция выполнена успешно\n", "success")
        else:
            messages.insert("end", "Код на Python не сформирован: исправьте ошибки в исходной программе\n")

        messages.configure(state="disabled")

    def format_tokens(self, result: TranslationResult) -> str:
        lines = [f"{'№':>4}  {'Тип':<16} {'Строка':>6} {'Поз.':>5}  Значение"]
        for i, token in enumerate(result.tokens):
            lines.append(f"{i:>4}  {token.type.name:<16} {token.line:>6} {token.column:>5}  {token.value}")
        return "\n".join(lines)

    def format_symbols(self, result: TranslationResult) -> str:
        if not result.symbol_table:
            return ""
        lines = [f"{'Имя':<15} {'Тип':<12} {'Вид':<12} {'Область':<20} {'Позиция'}"]
        for sym in result.symbol_table.all_symbols:
            lines.append(f"{sym.name:<15} {sym.type:<12} {sym.kind.name:<12} "
                         f"{sym.scope:<20} {sym.line}:{sym.column}")
        return "\n".join(lines)

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Открыть файл с кодом C#",
            filetypes=[("Файлы C#", "*.cs"), ("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")])
        if not path:
            return

        try:
            with open(path, "rb") as file:
                data = file.read()
            try:
                code = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                code = data.decode("cp1251")
        except (OSError, UnicodeDecodeError) as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл: {e}")
            return

        self.source_text.delete("1.0", "end")
        self.source_text.insert("1.0", code.replace("\r\n", "\n"))
        self.status.set(f"Загружен файл: {path}")

    def save_result(self):
        code = self.result_text.get("1.0", "end-1c")
        if not code.strip():
            messagebox.showinfo("Сохранение", "Нет результата для сохранения: сначала выполните трансляцию")
            return

        path = filedialog.asksaveasfilename(
            title="Сохранить код Python",
            defaultextension=".py",
            filetypes=[("Файлы Python", "*.py"), ("Все файлы", "*.*")])
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as file:
                file.write(code + "\n")
        except OSError as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить файл: {e}")
            return

        self.status.set(f"Результат сохранён: {path}")

    def clear(self):
        self.source_text.delete("1.0", "end")
        self.set_text(self.result_text, "")
        for text in self.detail_texts.values():
            self.set_text(text, "")
        self.status.set("Поля очищены")


def main():
    root = tk.Tk()
    TranslatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
