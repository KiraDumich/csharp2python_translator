import keyword
from typing import List, Optional

from parser import ASTNode, SymbolKind


class CodeGenerator:
    TYPE_MAP = {
        "int": "int",
        "float": "float",
        "double": "float",
        "string": "str",
        "bool": "bool",
        "char": "str",
        "byte": "int",
        "long": "int",
        "void": "None",
    }

    # Значения полей по умолчанию, как в C#
    DEFAULT_VALUES = {
        "int": "0", "byte": "0", "long": "0",
        "float": "0.0", "double": "0.0",
        "bool": "False", "string": "None", "char": "'\\0'",
    }
    INTEGER_TYPES = ("byte", "int", "long")

    OPERATOR_MAP = {"&&": "and", "||": "or", "!": "not"}

    # Приоритеты операций Python: по ним расставляются скобки
    PRECEDENCE = {
        "or": 1, "and": 2, "not": 3,
        "==": 4, "!=": 4, "<": 4, ">": 4, "<=": 4, ">=": 4,
        "|": 5, "^": 6, "&": 7,
        "+": 9, "-": 9,
        "*": 10, "/": 10, "%": 10,
    }
    COMPARISON_PRECEDENCE = 4
    UNARY_PRECEDENCE = 11
    ATOM_PRECEDENCE = 12

    def __init__(self):
        self.output = []
        self.indent_level = 0
        self.indent_size = 4
        self.errors = []
        self.warnings = []
        self.in_method = False

        self.statement_generators = {
            "Program": self.generate_program,
            "Comment": self.generate_comment,
            "ClassDeclaration": self.generate_class,
            "FieldDeclaration": self.generate_declaration,
            "MethodDeclaration": self.generate_method,
            "LocalDeclarationStatement": self.generate_declaration,
            "AssignmentStatement": self.generate_assignment,
            "ReturnStatement": self.generate_return,
            "IfStatement": self.generate_if,
            "WhileStatement": self.generate_while,
            "BlockStatement": self.generate_block_statement,
            "UnaryIncrement": self.generate_increment,
            "UnaryDecrement": self.generate_increment,
            "ExpressionStatement": self.generate_expression_statement,
        }

    def generate(self, ast: ASTNode) -> str:
        self.output = []
        self.indent_level = 0
        self.generate_node(ast)
        return "\n".join(self.output)

    def emit(self, line: str):
        self.output.append(" " * (self.indent_level * self.indent_size) + line)

    def indent(self):
        self.indent_level += 1

    def dedent(self):
        self.indent_level = max(0, self.indent_level - 1)

    def generate_node(self, node: ASTNode):
        generator = self.statement_generators.get(node.type)
        if not generator:
            self._warning(f"неизвестный тип узла AST '{node.type}', узел пропущен", node)
            return

        level = self.indent_level
        try:
            generator(node)
        except IndexError:
            self._error(f"узел {node.type}: отсутствует обязательный дочерний узел", node)
        self.indent_level = level

    def generate_program(self, node: ASTNode):
        for child in node.children:
            self.generate_node(child)

    def generate_comment(self, node: ASTNode):
        if node.value.startswith("//"):
            self.emit("#" + node.value[2:].rstrip())
            return

        text = node.value[2:-2].replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
        lines = [line.strip() if i else line.rstrip() for i, line in enumerate(text.split("\n"))]
        if len(lines) == 1:
            lines = [text]
        if lines[-1].endswith('"'):
            lines[-1] += " "
        lines[0] = '"""' + lines[0]
        lines[-1] += '"""'
        for line in lines:
            self.emit(line)

    def generate_class(self, node: ASTNode):
        if not node.value:
            self._error("узел ClassDeclaration: отсутствует имя класса", node)
            return

        self.emit(f"class {self.name(node.value)}:")
        self.generate_block(node.children[0].children if node.children else [])

    def generate_method(self, node: ASTNode):
        if not node.value:
            self._error("узел MethodDeclaration: отсутствует имя метода", node)
            return

        return_type = self.map_type(node.children[0])
        params = [f"{self.name(param.value)}: {self.map_type(param.children[0])}"
                  for param in node.children[1].children]

        self.emit(f"def {self.name(node.value)}({', '.join(params)}) -> {return_type}:")
        self.in_method = True
        self.generate_block(node.children[2].children if len(node.children) > 2 else [])
        self.in_method = False

    def generate_declaration(self, node: ASTNode):
        line = f"{self.name(node.children[1].value)}: {self.map_type(node.children[0])}"
        if len(node.children) > 2:
            line += f" = {self.expression(node.children[2])}"
        elif node.type == "FieldDeclaration" and node.children[0].value in self.DEFAULT_VALUES:
            line += f" = {self.DEFAULT_VALUES[node.children[0].value]}"
        self.emit(line)

    def generate_assignment(self, node: ASTNode):
        self.emit(f"{self.expression(node.children[0])} = {self.expression(node.children[1])}")

    def generate_return(self, node: ASTNode):
        if node.children:
            self.emit(f"return {self.expression(node.children[0])}")
        else:
            self.emit("return")

    def generate_if(self, node: ASTNode, keyword_: str = "if"):
        self.emit(f"{keyword_} {self.expression(node.children[0])}:")
        self.generate_block(self.body_statements(node, 1))

        if len(node.children) > 2:
            if node.children[2].type == "IfStatement":
                self.generate_if(node.children[2], "elif")
            else:
                self.emit("else:")
                self.generate_block(self.body_statements(node, 2))

    def generate_while(self, node: ASTNode):
        self.emit(f"while {self.expression(node.children[0])}:")
        self.generate_block(self.body_statements(node, 1))

    def generate_block_statement(self, node: ASTNode):
        # Блок { ... } в Python не выделяется: инструкции идут на текущем уровне
        for child in node.children:
            self.generate_node(child)

    def generate_increment(self, node: ASTNode):
        op = "+=" if node.type == "UnaryIncrement" else "-="
        self.emit(f"{self.expression(node.children[0])} {op} 1")

    def generate_expression_statement(self, node: ASTNode):
        self.emit(self.expression(node.children[0]))

    def body_statements(self, node: ASTNode, index: int) -> List[ASTNode]:
        if len(node.children) <= index:
            return []
        body = node.children[index]
        return body.children if body.type == "BlockStatement" else [body]

    def generate_block(self, statements: List[ASTNode]):
        self.indent()
        start = len(self.output)
        for stmt in statements:
            self.generate_node(stmt)
        # Блок без инструкций (или только с комментариями) в Python недопустим
        if all(line.lstrip().startswith("#") for line in self.output[start:]):
            self.emit("pass")
        self.dedent()

    def map_type(self, node: ASTNode) -> str:
        if node.value not in self.TYPE_MAP:
            self._error(f"неизвестный тип данных '{node.value}'", node)
            return str(node.value)
        return self.TYPE_MAP[node.value]

    # Выражения

    def expression(self, node: ASTNode) -> str:
        if node.type == "NumberLiteral":
            return node.value.rstrip("fFdDlL")

        if node.type == "CharLiteral":
            return node.value

        if node.type == "StringLiteral":
            return self.string_literal(node.value)

        if node.type == "BoolLiteral":
            return "True" if node.value == "true" else "False"

        if node.type == "NullLiteral":
            return "None"

        if node.type == "Identifier":
            return self.qualified_name(node)

        if node.type == "MethodCall":
            args = ", ".join(self.expression(arg) for arg in node.children[0].children)
            return f"{self.qualified_name(node)}({args})"

        if node.type == "LogicalNot":
            return f"not {self.operand(node.children[0], self.PRECEDENCE['not'], False)}"

        if node.type == "UnaryExpression":
            return f"{node.value}{self.operand(node.children[0], self.UNARY_PRECEDENCE, False)}"

        if node.type in ("BinaryExpression", "LogicalAnd", "LogicalOr"):
            op = self.OPERATOR_MAP.get(node.value, node.value)
            if op not in self.PRECEDENCE:
                self._error(f"неизвестная операция '{node.value}'", node)
                return ""
            precedence = self.PRECEDENCE[op]
            left = self.operand(node.children[0], precedence, False)
            right = self.operand(node.children[1], precedence, True)

            # В C# строка складывается с любым типом, в Python - только со строкой
            if op == "+" and node.data_type == "string":
                left = self.to_string(node.children[0], left)
                right = self.to_string(node.children[1], right)

            # Деление целых в C# отбрасывает дробную часть
            if op == "/" and node.data_type in self.INTEGER_TYPES:
                return f"int({left} / {right})"

            return f"{left} {op} {right}"

        self._warning(f"неизвестный тип узла AST '{node.type}', узел пропущен", node)
        return ""

    def operand(self, node: ASTNode, parent_precedence: int, is_right: bool) -> str:
        text = self.expression(node)
        precedence = self.precedence(node)

        needs_parens = precedence < parent_precedence or (is_right and precedence == parent_precedence)
        # a == b == c в Python - цепочка сравнений, а не (a == b) == c
        if precedence == parent_precedence == self.COMPARISON_PRECEDENCE:
            needs_parens = True

        return f"({text})" if needs_parens else text

    def precedence(self, node: ASTNode) -> int:
        if node.type in ("BinaryExpression", "LogicalAnd", "LogicalOr"):
            op = self.OPERATOR_MAP.get(node.value, node.value)
            return self.PRECEDENCE.get(op, self.ATOM_PRECEDENCE)
        if node.type == "LogicalNot":
            return self.PRECEDENCE["not"]
        if node.type == "UnaryExpression":
            return self.UNARY_PRECEDENCE
        return self.ATOM_PRECEDENCE

    def to_string(self, node: ASTNode, text: str) -> str:
        if node.data_type in ("string", "char", None):
            return text
        return f"str({text})"

    def qualified_name(self, node: ASTNode) -> str:
        # Поля и методы класса из тела метода доступны только через имя класса
        symbol = node.symbol
        if self.in_method and symbol and symbol.kind in (SymbolKind.FIELD, SymbolKind.METHOD):
            return f"{self.name(symbol.scope)}.{self.name(node.value)}"
        return self.name(node.value)

    def name(self, identifier: str) -> str:
        # Имена, зарезервированные в Python или занятые генератором, получают суффикс
        if keyword.iskeyword(identifier) or identifier in ("str", "int"):
            return identifier + "_"
        return identifier

    def string_literal(self, value: str) -> str:
        if not value.startswith("@"):
            return value

        content = value[2:-1]
        if "\n" in content or content.endswith("\\"):
            escaped = content.replace("\\", "\\\\").replace("\r", "").replace("\n", "\\n")
            return f'"{escaped}"'
        return f'r"{content}"'

    def _error(self, message: str, node: Optional[ASTNode] = None):
        pos = f' [строка {node.line}, поз. {node.column + 1}]' if node else ''
        self.errors.append(f'Ошибка генерации{pos}: {message}')

    def _warning(self, message: str, node: Optional[ASTNode] = None):
        pos = f' [строка {node.line}, поз. {node.column + 1}]' if node else ''
        self.warnings.append(f'Предупреждение{pos}: {message}')
