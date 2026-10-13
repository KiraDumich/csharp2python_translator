import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Tuple


class TokenType(Enum):
    # Ключевые слова C#
    KEYWORD = auto()

    # Идентификаторы
    IDENTIFIER = auto()

    # Литералы
    NUMBER_LITERAL = auto()  # int, float, double
    STRING_LITERAL = auto()  # "hello"
    CHAR_LITERAL = auto()  # 'a'
    BOOL_LITERAL = auto()  # true, false
    NULL_LITERAL = auto()  # null

    # Операторы
    OPERATOR = auto()

    # Разделители и пунктуация
    PUNCTUATION = auto()

    # Комментарии
    COMMENT_SINGLE = auto()
    COMMENT_MULTI = auto()

    # Пробелы
    WHITESPACE = auto()


@dataclass
class Token:
    type: TokenType
    value: str
    line: int
    column: int

    def __repr__(self):
        return f"Token({self.type.name}, '{self.value}', line={self.line}, col={self.column})"


@dataclass
class LexicalError:
    code: str
    message: str
    line: int
    column: int

    def __str__(self):
        return f"Лексическая ошибка {self.code} [строка {self.line}, поз. {self.column + 1}]: {self.message}"


class CSharpLexer:
    DATA_TYPES = {"int", "float", "double", "string", "bool", "char", "void", "byte", "long"}

    def __init__(self):
        self.errors: List[LexicalError] = []

        self.token_specs = [
            # Комментарии
            (TokenType.COMMENT_SINGLE, r'//.*?$'),
            (TokenType.COMMENT_MULTI, r'/\*.*?\*/'),

            # Пробелы (игнорируем)
            (TokenType.WHITESPACE, r'[ \t\n\r]+'),

            # Литералы true, false, null (до ключевых слов, иначе попадут в KEYWORD)
            (TokenType.BOOL_LITERAL, r'\b(true|false)\b'),
            (TokenType.NULL_LITERAL, r'\bnull\b'),

            # Ключевые слова C#
            (TokenType.KEYWORD,
             r'\b(abstract|as|base|bool|break|byte|case|catch|char|checked|class|const|continue|decimal|default|delegate|do|double|else|enum|event|explicit|extern|false|finally|fixed|float|for|foreach|goto|if|implicit|in|int|interface|internal|is|lock|long|namespace|new|null|object|operator|out|override|params|private|protected|public|readonly|ref|return|sbyte|sealed|short|sizeof|stackalloc|static|string|struct|switch|this|throw|true|try|typeof|uint|ulong|unchecked|unsafe|ushort|using|virtual|void|volatile|while)\b'),

            # Буквальные литералы
            (TokenType.STRING_LITERAL, r'@"[^"]*"|"[^"\\]*(\\.[^"\\]*)*"'),
            (TokenType.CHAR_LITERAL, r"'(\\u[0-9A-Fa-f]{4}|\\.|[^'\\\n])'"),
            (TokenType.NUMBER_LITERAL, r'\b\d+(\.\d+)?([eE][+-]?\d+)?[fFdDlL]?\b'),

            # Идентификаторы
            (TokenType.IDENTIFIER, r'\b[A-Za-z_][A-Za-z0-9_]*\b'),

            # Операторы
            (TokenType.OPERATOR, r'==|!=|<=|>=|\+\+|--|<<|>>|&&|\|\||[+\-*/%=<>!&|^~?:]'),

            # Разделители
            (TokenType.PUNCTUATION, r'[\(\)\{\}\[\];,\.]'),
        ]

        pattern_parts = []
        for tt, pattern in self.token_specs:
            group_name = tt.name
            pattern_parts.append(f'(?P<{group_name}>{pattern})')

        combined_pattern = '|'.join(pattern_parts)
        self.token_re = re.compile(combined_pattern, re.DOTALL | re.MULTILINE)

    def tokenize(self, code: str) -> List[Token]:
        tokens = []

        for mo in self.token_re.finditer(code):
            for token_type in TokenType:
                group_name = token_type.name
                token_value = mo.group(group_name)

                if token_value is not None:
                    start_pos = mo.start()
                    line_num = code.count('\n', 0, start_pos) + 1
                    last_newline = code.rfind('\n', 0, start_pos)
                    column = start_pos - (last_newline + 1)

                    if token_type != TokenType.WHITESPACE:
                        tokens.append(Token(token_type, token_value, line_num, column))
                    break

        self.errors = self.find_errors(code, tokens)
        return tokens

    def tokenize_simple(self, code: str) -> List[Tuple[str, str]]:
        tokens = self.tokenize(code)
        return [(t.type.name, t.value) for t in tokens]

    def find_errors(self, code: str, tokens: List[Token]) -> List[LexicalError]:
        errors = []

        # Фрагменты текста, не подошедшие ни под один шаблон
        pos = 0
        prev_value = None
        for mo in self.token_re.finditer(code):
            if mo.start() > pos:
                errors.append(self.classify_gap(code, pos, mo.start(), prev_value))
            pos = mo.end()
            if not mo.group().isspace():
                prev_value = mo.group()
        if pos < len(code):
            errors.append(self.classify_gap(code, pos, len(code), prev_value))

        # Ошибки, которые видны только по соседним токенам
        for i, token in enumerate(tokens):
            next_token = tokens[i + 1] if i + 1 < len(tokens) else None
            adjacent = (next_token is not None and next_token.line == token.line
                        and next_token.column == token.column + len(token.value))

            if (token.type == TokenType.STRING_LITERAL and not token.value.startswith('@')
                    and '\n' in token.value):
                errors.append(LexicalError("E1", "незакрытый строковый литерал",
                                           token.line, token.column))

            if (token.type == TokenType.NUMBER_LITERAL and '.' in token.value
                    and adjacent and next_token.value == '.'):
                errors.append(LexicalError("E3", f"некорректный числовой литерал '{token.value}.': "
                                                 f"несколько десятичных точек",
                                           token.line, token.column))

            if (token.type == TokenType.OPERATOR and token.value == '/'
                    and adjacent and next_token.value == '*'):
                errors.append(LexicalError("E4", "незакрытый многострочный комментарий",
                                           token.line, token.column))

        # Одна ошибка одного вида на строку
        unique = {}
        for error in sorted(errors, key=lambda e: (e.line, e.column)):
            unique.setdefault((error.code, error.line), error)
        return list(unique.values())

    def classify_gap(self, code: str, start: int, end: int, prev_value) -> LexicalError:
        text = code[start:end]

        if '"' in text:
            start += text.index('"')
            error_code, message = "E1", "незакрытый строковый литерал"
        elif "'" in text:
            start += text.index("'")
            error_code, message = "E2", "некорректный символьный литерал"
        elif text[0].isdigit():
            # Начало числа могло быть распознано отдельными токенами (3.14x -> '3', '.', '14x')
            while start > 0 and (code[start - 1].isdigit() or code[start - 1] == '.'):
                start -= 1
            text = code[start:end]
            if prev_value in self.DATA_TYPES:
                error_code, message = "E6", f"некорректный идентификатор '{text}': имя начинается с цифры"
            else:
                error_code, message = "E3", f"некорректный числовой литерал '{text}'"
        else:
            error_code, message = "E5", f"недопустимый символ '{text}'"

        line = code.count('\n', 0, start) + 1
        column = start - (code.rfind('\n', 0, start) + 1)
        return LexicalError(error_code, message, line, column)


if __name__ == "__main__":
    lexer = CSharpLexer()

    csharp_code = """
    public class Calculator {
        private int _count = 0;

        public int Add(int a, int b) {
            // Сложение двух чисел
            return a + b;
        }

        public void Test() {
            string text = "Hello\\nWorld";
            char c = 'A';
            bool flag = true;
            int? nullable = null;
        }
    }
    """

    print("Исходный код:")
    print(csharp_code)
    print("\nТокены:")
    tokens = lexer.tokenize_simple(csharp_code)
    for i, (token_type, value) in enumerate(tokens):
        print(f"{token_type:20} : {value}")