from typing import List, Dict, Optional
from enum import Enum, auto
from dataclasses import dataclass, field
from lexer import CSharpLexer, Token, TokenType

@dataclass
class ASTNode:
    type: str
    value: any = None
    children: List['ASTNode'] = field(default_factory=list)
    line: int = 0
    column: int = 0
    # Заполняются на следующих фазах: тип выражения, символ идентификатора, область блока
    data_type: Optional[str] = None
    symbol: Optional['Symbol'] = None
    scope: Optional[str] = None

    def add_child(self, child: 'ASTNode'):
        if child:
            self.children.append(child)

    def __repr__(self, level=0):
        indent = "  " * level
        result = f"{indent}{self.type}"
        if self.value:
            result += f": {self.value}"
        result += "\n"
        for child in self.children:
            result += child.__repr__(level + 1)
        return result

class SymbolKind(Enum):
    VARIABLE = auto()
    METHOD = auto()
    CLASS = auto()
    PARAMETER = auto()
    FIELD = auto()

@dataclass
class Symbol:
    name: str
    kind: SymbolKind
    type: str
    scope: str
    line: int
    column: int

class SymbolTable:
    def __init__(self):
        self.symbols: Dict[str, List[Symbol]] = {}
        self.current_scope = "global"
        self.scope_stack = ["global"]
        self.all_symbols: List[Symbol] = []

    def enter_scope(self, scope_name: str):
        self.scope_stack.append(scope_name)
        self.current_scope = scope_name

    def exit_scope(self):
        self.scope_stack.pop()
        self.current_scope = self.scope_stack[-1]

    def insert(self, name: str, kind: SymbolKind, type_: str, line: int, col: int) -> bool:
        if self.current_scope not in self.symbols:
            self.symbols[self.current_scope] = []

        for sym in self.symbols[self.current_scope]:
            if sym.name == name:
                return False

        symbol = Symbol(name, kind, type_, self.current_scope, line, col)
        self.symbols[self.current_scope].append(symbol)
        self.all_symbols.append(symbol)
        return True

    def lookup(self, name: str) -> Optional[Symbol]:
        for scope in reversed(self.scope_stack):
            if scope in self.symbols:
                for sym in self.symbols[scope]:
                    if sym.name == name:
                        return sym
        return None

    def print_table(self):
        print("\nТаблица символов")
        print(f"{'Имя':<15} {'Тип':<12} {'Вид':<12} {'Область':<20} {'Позиция'}")
        for sym in self.all_symbols:
            print(f"{sym.name:<15} {sym.type:<12} {sym.kind.name:<12} "
                  f"{sym.scope:<20} {sym.line}:{sym.column}")

class Parser:
    COMMENT_TYPES = (TokenType.COMMENT_SINGLE, TokenType.COMMENT_MULTI)

    # Уровни бинарных операций от низшего приоритета к высшему;
    # операции *, /, % разбирает parse_term
    BINARY_LEVELS = [
        ("||",),
        ("&&",),
        ("|",),
        ("^",),
        ("&",),
        ("==", "!="),
        ("<", ">", "<=", ">="),
        ("+", "-"),
    ]

    def __init__(self, lexer: CSharpLexer):
        self.lexer = lexer
        self.symbol_table = SymbolTable()
        self.tokens: List[Token] = []
        self.all_tokens: List[Token] = []
        self.current_pos = 0
        self.block_count = 0
        self.errors: List[str] = []
        self.warnings: List[str] = []

        self.data_types = {"int", "float", "double", "string", "bool", "char", "void", "byte", "long"}

    def current_token(self) -> Optional[Token]:
        if self.current_pos < len(self.tokens):
            return self.tokens[self.current_pos]
        return None

    def peek_next(self) -> Optional[Token]:
        if self.current_pos + 1 < len(self.tokens):
            return self.tokens[self.current_pos + 1]
        return None

    def peek_nth(self, n: int) -> Optional[Token]:
        if self.current_pos + n < len(self.tokens):
            return self.tokens[self.current_pos + n]
        return None

    def next_token(self):
        self.current_pos += 1

    def match(self, expected_value: str) -> bool:
        token = self.current_token()
        if token and token.value == expected_value:
            self.next_token()
            return True
        return False

    def expect(self, expected_value: str) -> bool:
        if not self.match(expected_value):
            token = self.current_token()
            self.error(f"Ожидалось '{expected_value}', найдено '{token.value if token else 'EOF'}'")
        return True

    def expect_type(self, expected_type: TokenType) -> Token:
        token = self.current_token()
        if token and token.type == expected_type:
            self.next_token()
            return token
        self.error(f"Ожидался {expected_type.name}, найдено '{token.value if token else 'EOF'}'")

    def parse(self, code: str):
        self.all_tokens = self.lexer.tokenize(code)
        self.tokens = []
        self.current_pos = 0
        self.block_count = 0
        self.symbol_table = SymbolTable()
        self.errors = []
        self.warnings = []

        # При лексических ошибках синтаксический анализ не выполняется
        if self.lexer.errors:
            return None

        self.tokens = self.filter_comments(self.all_tokens)

        try:
            ast = self.parse_program()

            if self.current_token():
                self.error(f"Лишние токены после объявления класса: '{self.current_token().value}'")

            return ast
        except SyntaxError as e:
            self.errors.append(f"Синтаксическая ошибка {e}")
            return None

    def filter_comments(self, tokens: List[Token]) -> List[Token]:
        # Комментарий остаётся в потоке только там, где может начинаться инструкция
        result = []
        for i, token in enumerate(tokens):
            if token.type in self.COMMENT_TYPES:
                prev = next((t for t in reversed(result) if t.type not in self.COMMENT_TYPES), None)
                following = next((t for t in tokens[i + 1:] if t.type not in self.COMMENT_TYPES), None)
                at_statement_start = prev is None or (prev.type == TokenType.PUNCTUATION
                                                      and prev.value in ("{", "}", ";"))
                if not at_statement_start or (following and following.value == "else"):
                    self.warning("Комментарий внутри инструкции не перенесён в результат",
                                 token.line, token.column)
                    continue
            result.append(token)
        return result

    def is_comment(self, token: Optional[Token]) -> bool:
        return token is not None and token.type in self.COMMENT_TYPES

    def parse_comment(self) -> ASTNode:
        token = self.current_token()
        self.next_token()
        return ASTNode("Comment", token.value, line=token.line, column=token.column)

    # Грамматика

    def parse_program(self) -> ASTNode:
        program_node = ASTNode("Program")

        while self.is_comment(self.current_token()):
            program_node.add_child(self.parse_comment())

        class_node = self.parse_class_declaration()
        if class_node:
            program_node.add_child(class_node)
        else:
            self.error("Программа должна содержать объявление класса")

        while self.is_comment(self.current_token()):
            program_node.add_child(self.parse_comment())

        return program_node

    def parse_class_declaration(self) -> Optional[ASTNode]:
        if not self.match("class"):
            return None

        class_node = ASTNode("ClassDeclaration")

        token = self.expect_type(TokenType.IDENTIFIER)
        if token:
            class_node.value = token.value
            self.symbol_table.insert(token.value, SymbolKind.CLASS, "class",
                                     token.line, token.column)
            self.symbol_table.enter_scope(token.value)

        self.expect("{")

        body_node = self.parse_class_body()
        if body_node:
            class_node.add_child(body_node)

        self.expect("}")
        self.symbol_table.exit_scope()

        return class_node

    def parse_class_body(self) -> ASTNode:
        body_node = ASTNode("ClassBody")

        while self.current_token() and self.current_token().value != "}":
            token = self.current_token()

            if self.is_comment(token):
                body_node.add_child(self.parse_comment())
                continue

            if token.type == TokenType.KEYWORD and token.value in self.data_types:
                third_token = self.peek_nth(2)

                if third_token and third_token.value == "(":
                    member_node = self.parse_method_declaration()
                else:
                    member_node = self.parse_field_declaration()

                if member_node:
                    member_node.line, member_node.column = token.line, token.column
                    body_node.add_child(member_node)
                    continue

            self.warning(f"Пропущен непонятный токен в теле класса: {token.value}",
                         token.line, token.column)
            self.next_token()

        return body_node

    def parse_field_declaration(self) -> Optional[ASTNode]:
        field_node = ASTNode("FieldDeclaration")

        type_token = self.current_token()
        if not type_token or type_token.value not in self.data_types:
            return None

        field_type = type_token.value
        field_node.add_child(ASTNode("Type", field_type))
        self.next_token()

        name_token = self.expect_type(TokenType.IDENTIFIER)

        field_node.add_child(ASTNode("Identifier", name_token.value))

        self.symbol_table.insert(name_token.value, SymbolKind.FIELD, field_type,
                                 name_token.line, name_token.column)

        if self.current_token() and self.current_token().value == "=":
            self.next_token()
            expr_node = self.parse_expression()
            if expr_node:
                field_node.add_child(expr_node)

        self.expect(";")

        return field_node

    def parse_method_declaration(self) -> Optional[ASTNode]:
        method_node = ASTNode("MethodDeclaration")

        type_token = self.current_token()
        if not type_token or type_token.value not in self.data_types:
            return None

        return_type = type_token.value
        method_node.add_child(ASTNode("ReturnType", return_type))
        self.next_token()

        name_token = self.expect_type(TokenType.IDENTIFIER)

        method_node.value = name_token.value

        self.symbol_table.insert(name_token.value, SymbolKind.METHOD, return_type,
                                name_token.line, name_token.column)
        
        method_scope = f"{self.symbol_table.current_scope}.{name_token.value}"
        self.symbol_table.enter_scope(method_scope)

        self.expect("(")

        params_node = self.parse_parameter_list()
        if params_node:
            method_node.add_child(params_node)

        self.expect(")")

        self.expect("{")

        body_node = self.parse_method_body()
        if body_node:
            method_node.add_child(body_node)

        self.expect("}")
        self.symbol_table.exit_scope()

        return method_node

    def parse_parameter_list(self) -> ASTNode:
        params_node = ASTNode("Parameters")

        token = self.current_token()
        if not token or token.value == ")":
            return params_node

        while True:
            param_node = self.parse_parameter()
            if param_node:
                params_node.add_child(param_node)
            else:
                break

            if self.current_token() and self.current_token().value == ",":
                self.next_token()
                continue
            else:
                break

        return params_node

    def parse_parameter(self) -> Optional[ASTNode]:
        type_token = self.current_token()
        if not type_token or type_token.value not in self.data_types:
            return None

        param_type = type_token.value
        self.next_token()

        name_token = self.expect_type(TokenType.IDENTIFIER)

        param_node = ASTNode("Parameter", name_token.value)
        param_node.add_child(ASTNode("Type", param_type))

        self.symbol_table.insert(name_token.value, SymbolKind.PARAMETER, param_type,
                                name_token.line, name_token.column)

        return param_node

    def parse_method_body(self) -> ASTNode:
        body_node = ASTNode("MethodBody")

        while self.current_token() and self.current_token().value != "}":
            stmt = self.parse_statement()
            if stmt:
                body_node.add_child(stmt)
            else:
                break

        return body_node

    def parse_statement(self) -> Optional[ASTNode]:
        token = self.current_token()
        if not token:
            return None

        if self.is_comment(token):
            return self.parse_comment()

        next_token = self.peek_next()
        next_value = next_token.value if next_token else None
        stmt = None

        if token.type == TokenType.KEYWORD and token.value in self.data_types:
            stmt = self.parse_declaration_statement()

        elif token.type == TokenType.OPERATOR and token.value in ("++", "--"):
            stmt = self.parse_increment_statement()

        elif token.type == TokenType.IDENTIFIER:
            if next_value in ("++", "--"):
                stmt = self.parse_increment_statement()
            elif next_value == "(":
                stmt = self.parse_call_statement()
            elif next_value == ".":
                self.error(f"Неподдерживаемая конструкция языка: обращение к члену "
                           f"'{token.value}.{self.peek_nth(2).value if self.peek_nth(2) else ''}'")
            else:
                stmt = self.parse_assignment_statement()

        elif token.value == "return":
            stmt = self.parse_return_statement()

        elif token.value == "if":
            stmt = self.parse_if_statement()

        elif token.value == "while":
            stmt = self.parse_while_statement()

        elif token.value == "{":
            stmt = self.parse_block_statement()

        if stmt is None:
            if token.value != "}":
                self.error(f"Неподдерживаемая конструкция языка: '{token.value}'")
            return None

        stmt.line, stmt.column = token.line, token.column
        return stmt

    def parse_declaration_statement(self) -> Optional[ASTNode]:
        decl_node = ASTNode("LocalDeclarationStatement")

        type_token = self.current_token()
        if not type_token or type_token.value not in self.data_types:
            return None

        var_type = type_token.value
        decl_node.add_child(ASTNode("Type", var_type))
        self.next_token()

        name_token = self.expect_type(TokenType.IDENTIFIER)

        var_name = name_token.value
        decl_node.add_child(ASTNode("Identifier", var_name))

        self.symbol_table.insert(var_name, SymbolKind.VARIABLE, var_type,
                                 name_token.line, name_token.column)

        if self.current_token() and self.current_token().value == "=":
            self.next_token()
            expr_node = self.parse_expression()
            if expr_node:
                decl_node.add_child(expr_node)

        self.expect(";")

        return decl_node

    def parse_assignment_statement(self) -> Optional[ASTNode]:
        assign_node = ASTNode("AssignmentStatement")

        var_token = self.expect_type(TokenType.IDENTIFIER)

        var_name = var_token.value
        assign_node.add_child(ASTNode("Identifier", var_name))

        self.expect("=")

        expr_node = self.parse_expression()
        if expr_node:
            assign_node.add_child(expr_node)

        self.expect(";")

        return assign_node

    def parse_increment_statement(self) -> Optional[ASTNode]:
        token = self.current_token()

        # Префиксная (++x;) и постфиксная (x++;) формы как отдельная инструкция
        if token.type == TokenType.OPERATOR:
            op = token.value
            self.next_token()
            var_token = self.expect_type(TokenType.IDENTIFIER)
        else:
            var_token = self.expect_type(TokenType.IDENTIFIER)
            op = self.current_token().value
            self.next_token()

        node = ASTNode("UnaryIncrement" if op == "++" else "UnaryDecrement")
        node.add_child(ASTNode("Identifier", var_token.value,
                               line=var_token.line, column=var_token.column))

        self.expect(";")

        return node

    def parse_call_statement(self) -> Optional[ASTNode]:
        stmt_node = ASTNode("ExpressionStatement")
        stmt_node.add_child(self.parse_method_call())

        self.expect(";")

        return stmt_node

    def parse_method_call(self) -> Optional[ASTNode]:
        name_token = self.expect_type(TokenType.IDENTIFIER)
        call_node = ASTNode("MethodCall", name_token.value,
                            line=name_token.line, column=name_token.column)

        self.expect("(")

        args_node = ASTNode("Arguments")
        if self.current_token() and self.current_token().value != ")":
            while True:
                args_node.add_child(self.parse_expression())
                if not self.match(","):
                    break
        call_node.add_child(args_node)

        self.expect(")")

        return call_node

    def parse_return_statement(self) -> Optional[ASTNode]:
        return_node = ASTNode("ReturnStatement")

        self.expect("return")

        if self.current_token() and self.current_token().value != ";":
            expr_node = self.parse_expression()
            if expr_node:
                return_node.add_child(expr_node)

        self.expect(";")

        return return_node

    def parse_if_statement(self) -> Optional[ASTNode]:
        if_node = ASTNode("IfStatement")

        self.expect("if")

        self.expect("(")

        condition = self.parse_expression()
        if condition:
            if_node.add_child(condition)

        self.expect(")")

        then_stmt = self.parse_statement()
        if then_stmt:
            if_node.add_child(then_stmt)

        if self.current_token() and self.current_token().value == "else":
            self.next_token()
            else_stmt = self.parse_statement()
            if else_stmt:
                if_node.add_child(else_stmt)

        return if_node

    def parse_while_statement(self) -> Optional[ASTNode]:
        while_node = ASTNode("WhileStatement")

        self.expect("while")

        self.expect("(")

        condition = self.parse_expression()
        if condition:
            while_node.add_child(condition)

        self.expect(")")

        body = self.parse_statement()
        if body:
            while_node.add_child(body)

        return while_node

    def parse_block_statement(self) -> Optional[ASTNode]:
        block_node = ASTNode("BlockStatement")

        self.expect("{")

        # У каждого блока своя область видимости, вложенная в текущую
        self.block_count += 1
        block_node.scope = f"{self.symbol_table.current_scope}.block{self.block_count}"
        self.symbol_table.enter_scope(block_node.scope)

        while self.current_token() and self.current_token().value != "}":
            stmt = self.parse_statement()
            if stmt:
                block_node.add_child(stmt)
            else:
                break

        self.expect("}")
        self.symbol_table.exit_scope()

        return block_node

    def parse_expression(self) -> Optional[ASTNode]:
        return self.parse_binary(0)

    def parse_binary(self, level: int) -> Optional[ASTNode]:
        if level == len(self.BINARY_LEVELS):
            return self.parse_term()

        left = self.parse_binary(level + 1)

        while (self.current_token() and self.current_token().type == TokenType.OPERATOR
               and self.current_token().value in self.BINARY_LEVELS[level]):
            op_token = self.current_token()
            self.next_token()
            right = self.parse_binary(level + 1)

            if op_token.value == "&&":
                expr_node = ASTNode("LogicalAnd", op_token.value)
            elif op_token.value == "||":
                expr_node = ASTNode("LogicalOr", op_token.value)
            else:
                expr_node = ASTNode("BinaryExpression", op_token.value)
            expr_node.line, expr_node.column = op_token.line, op_token.column
            expr_node.add_child(left)
            expr_node.add_child(right)
            left = expr_node

        return left

    def parse_term(self) -> Optional[ASTNode]:
        left = self.parse_factor()
        if not left:
            return None

        while self.current_token() and self.current_token().value in ['*', '/', '%']:
            op = self.current_token().value
            self.next_token()
            right = self.parse_factor()
            if right:
                term_node = ASTNode("BinaryExpression", op)
                term_node.add_child(left)
                term_node.add_child(right)
                left = term_node

        return left

    def parse_factor(self) -> Optional[ASTNode]:
        token = self.current_token()
        if not token:
            self.error("Некорректное выражение: ожидался операнд")

        if token.type == TokenType.OPERATOR and token.value in ("!", "-", "~"):
            self.next_token()
            if token.value == "!":
                unary_node = ASTNode("LogicalNot", token.value, line=token.line, column=token.column)
            else:
                unary_node = ASTNode("UnaryExpression", token.value, line=token.line, column=token.column)
            unary_node.add_child(self.parse_factor())
            return unary_node

        if token.type == TokenType.NUMBER_LITERAL:
            self.next_token()
            return ASTNode("NumberLiteral", token.value, line=token.line, column=token.column)

        if token.type == TokenType.STRING_LITERAL:
            self.next_token()
            return ASTNode("StringLiteral", token.value, line=token.line, column=token.column)

        if token.type == TokenType.CHAR_LITERAL:
            self.next_token()
            return ASTNode("CharLiteral", token.value, line=token.line, column=token.column)

        if token.type == TokenType.BOOL_LITERAL:
            self.next_token()
            return ASTNode("BoolLiteral", token.value, line=token.line, column=token.column)

        if token.type == TokenType.NULL_LITERAL:
            self.next_token()
            return ASTNode("NullLiteral", token.value, line=token.line, column=token.column)

        if token.type == TokenType.IDENTIFIER:
            next_token = self.peek_next()
            if next_token and next_token.value == "(":
                return self.parse_method_call()
            if next_token and next_token.value == ".":
                self.error(f"Неподдерживаемая конструкция языка: обращение к члену '{token.value}.'")

            self.next_token()
            return ASTNode("Identifier", token.value, line=token.line, column=token.column)

        if token.value == "(":
            self.next_token()
            expr = self.parse_expression()
            if expr and self.expect(")"):
                return expr

        self.error(f"Некорректное выражение: ожидался операнд, найдено '{token.value}'")

    def error(self, message: str):
        token = self.current_token()
        if token:
            raise SyntaxError(f"[строка {token.line}, поз. {token.column + 1}]: {message}")
        else:
            raise SyntaxError(f"[конец файла]: {message}")

    def warning(self, message: str, line: int = 0, column: int = 0):
        if line:
            self.warnings.append(f"Предупреждение [строка {line}, поз. {column + 1}]: {message}")
        else:
            self.warnings.append(f"Предупреждение: {message}")


def main():
    lexer = CSharpLexer()
    parser = Parser(lexer)

    test_code = """
    class Calculator {
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

    print("ЛЕКСИЧЕСКИЙ АНАЛИЗ")
    tokens = lexer.tokenize_simple(test_code)
    print("Токены:")
    for i, (ttype, value) in enumerate(tokens):
        print(f"{i:3}: {ttype:20} '{value}'")

    
    print("\n\nСИНТАКСИЧЕСКИЙ АНАЛИЗ")
    ast = parser.parse(test_code)

    for message in parser.errors + parser.warnings:
        print(message)

    if ast:
        print("\nАбстрактное синтаксическое дерево (AST):")
        print(ast)
        parser.symbol_table.print_table()


if __name__ == "__main__":
    main()