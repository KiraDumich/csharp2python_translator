from dataclasses import dataclass, field
from typing import List, Optional

from lexer import CSharpLexer, Token
from parser import ASTNode, Parser, SymbolTable
from semantic import SemanticAnalyzer
from codegen import CodeGenerator


@dataclass
class TranslationResult:
    python_code: str = ""
    tokens: List[Token] = field(default_factory=list)
    ast: Optional[ASTNode] = None
    symbol_table: Optional[SymbolTable] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors


class Translator:
    """Последовательно запускает фазы трансляции: лексический, синтаксический,
    семантический анализ и генерацию кода. Фаза с ошибками останавливает трансляцию."""

    def translate(self, code: str) -> TranslationResult:
        result = TranslationResult()

        lexer = CSharpLexer()
        parser = Parser(lexer)

        ast = parser.parse(code)
        result.tokens = parser.all_tokens
        result.symbol_table = parser.symbol_table

        if lexer.errors:
            result.errors = [str(error) for error in lexer.errors]
            return result

        result.ast = ast
        result.errors.extend(parser.errors)
        result.warnings.extend(parser.warnings)
        if not ast:
            return result

        analyzer = SemanticAnalyzer(parser.symbol_table)
        analyzer.analyze(ast)
        result.errors.extend(analyzer.errors)
        result.warnings.extend(analyzer.warnings)
        if analyzer.errors:
            return result

        generator = CodeGenerator()
        python_code = generator.generate(ast)
        result.errors.extend(generator.errors)
        result.warnings.extend(generator.warnings)
        if not generator.errors:
            result.python_code = python_code

        return result


def main():
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

    result = Translator().translate(test_code)

    for message in result.errors + result.warnings:
        print(message)

    if result.success:
        print(result.python_code)


if __name__ == "__main__":
    main()
