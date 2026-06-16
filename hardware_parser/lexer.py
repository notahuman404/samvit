"""
Lexer for HWDL Compiler

Tokenizes HWDL source code into a token stream.
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Iterator
from enum import Enum
from .ast_nodes import SourceLoc, PinDirection


class TokenKind(Enum):
    """Token kind enumeration."""
    # Keywords
    KW_HWDL = "hwdl"
    KW_PART = "part"
    KW_POWER = "power"
    KW_MODULE = "module"
    KW_NET = "net"
    KW_CONNECT = "connect"
    KW_CONSTRAINT = "constraint"
    KW_PLACEMENT = "placement"
    KW_ROUTING = "routing"
    KW_VALIDATE = "validate"
    KW_SIMULATE = "simulate"
    KW_TARGET = "target"
    KW_PINS = "pins"
    KW_TO = "to"
    KW_TRUE = "true"
    KW_FALSE = "false"
    
    # Pin directions
    PINDIR_POWER_IN = "power_in"
    PINDIR_POWER_OUT = "power_out"
    PINDIR_POWER_GND = "power_gnd"
    PINDIR_INPUT = "input"
    PINDIR_OUTPUT = "output"
    PINDIR_BIDIR = "bidir"
    PINDIR_PASSIVE = "passive"
    PINDIR_OPEN_DRAIN = "open_drain"
    PINDIR_NO_CONNECT = "no_connect"
    
    # Literals
    IDENT = "IDENT"
    STRING = "STRING"
    VERSION = "VERSION"
    NUMBER = "NUMBER"
    UNIT = "UNIT"
    BOOL = "BOOL"
    
    # Operators and punctuation
    ARROW = "->"
    DOT = "."
    COLON = ":"
    SEMICOLON = ";"
    LBRACE = "{"
    RBRACE = "}"
    LBRACKET = "["
    RBRACKET = "]"
    COMMA = ","
    
    # Special
    EOF = "EOF"
    ERROR = "ERROR"


@dataclass
class Token:
    """A lexical token."""
    kind: TokenKind
    text: str           # original text from source
    loc: SourceLoc


KEYWORDS = {
    "hwdl": TokenKind.KW_HWDL,
    "part": TokenKind.KW_PART,
    "power": TokenKind.KW_POWER,
    "module": TokenKind.KW_MODULE,
    "net": TokenKind.KW_NET,
    "connect": TokenKind.KW_CONNECT,
    "constraint": TokenKind.KW_CONSTRAINT,
    "placement": TokenKind.KW_PLACEMENT,
    "routing": TokenKind.KW_ROUTING,
    "validate": TokenKind.KW_VALIDATE,
    "simulate": TokenKind.KW_SIMULATE,
    "target": TokenKind.KW_TARGET,
    "pins": TokenKind.KW_PINS,
    "to": TokenKind.KW_TO,
    "true": TokenKind.KW_TRUE,
    "false": TokenKind.KW_FALSE,
    "power_in": TokenKind.PINDIR_POWER_IN,
    "power_out": TokenKind.PINDIR_POWER_OUT,
    "power_gnd": TokenKind.PINDIR_POWER_GND,
    "input": TokenKind.PINDIR_INPUT,
    "output": TokenKind.PINDIR_OUTPUT,
    "bidir": TokenKind.PINDIR_BIDIR,
    "passive": TokenKind.PINDIR_PASSIVE,
    "open_drain": TokenKind.PINDIR_OPEN_DRAIN,
    "no_connect": TokenKind.PINDIR_NO_CONNECT,
}

UNIT_SYMBOLS = [
    "kOhm", "MOhm", "Ohm",
    "mF", "uF", "nF", "pF", "F",
    "mH", "uH", "nH", "H",
    "MHz", "kHz", "GHz", "Hz",
    "mV", "uV", "V",
    "mA", "uA", "nA", "A",
    "ms", "us", "ns", "ps", "s",
    "%", "C",
]

class Lexer:
    """Tokenizes HWDL source code."""

    def __init__(self, text: str, filename: str = "<stdin>"):
        self.text = text
        self.filename = filename
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: List[Token] = []

    def current_char(self) -> Optional[str]:
        """Get the current character without consuming it."""
        if self.pos < len(self.text):
            return self.text[self.pos]
        return None

    def peek_char(self, offset: int = 1) -> Optional[str]:
        """Peek ahead by offset characters."""
        pos = self.pos + offset
        if pos < len(self.text):
            return self.text[pos]
        return None

    def consume(self, count: int = 1) -> str:
        """Consume and return count characters, updating line/col."""
        result = ""
        for _ in range(count):
            if self.pos < len(self.text):
                ch = self.text[self.pos]
                result += ch
                if ch == "\n":
                    self.line += 1
                    self.col = 1
                else:
                    self.col += 1
                self.pos += 1
        return result

    def skip_whitespace(self) -> None:
        """Skip whitespace and comments."""
        while True:
            ch = self.current_char()
            if ch in (" ", "\t", "\r", "\n"):
                self.consume()
            elif ch == "/" and self.peek_char() == "/":
                # Skip line comment
                self.consume(2)  # consume //
                while self.current_char() and self.current_char() != "\n":
                    self.consume()
                if self.current_char() == "\n":
                    self.consume()
            elif ch == "/" and self.peek_char() == "*":
                # Skip block comment
                self.consume(2)  # consume /*
                while self.current_char():
                    if self.current_char() == "*" and self.peek_char() == "/":
                        self.consume(2)  # consume */
                        break
                    self.consume()
            else:
                break

    def read_string(self) -> str:
        """Read a string literal, returning the content without quotes."""
        self.consume()  # consume opening "
        result = ""
        while self.current_char() and self.current_char() != '"':
            if self.current_char() == "\\":
                self.consume()  # consume backslash
                ch = self.current_char()
                if ch == '"':
                    result += '"'
                    self.consume()
                elif ch == "\\":
                    result += "\\"
                    self.consume()
                elif ch == "n":
                    result += "\n"
                    self.consume()
                elif ch == "t":
                    result += "\t"
                    self.consume()
                else:
                    result += ch
                    self.consume()
            else:
                result += self.current_char()
                self.consume()
        
        if self.current_char() == '"':
            self.consume()  # consume closing "
        
        return result

    def read_number(self) -> str:
        """Read a number literal."""
        result = ""
        if self.current_char() == "-":
            result += self.consume()
        
        while self.current_char() and self.current_char().isdigit():
            result += self.consume()
        
        if self.current_char() == "." and self.peek_char() and self.peek_char().isdigit():
            result += self.consume()  # consume .
            while self.current_char() and self.current_char().isdigit():
                result += self.consume()
        
        if self.current_char() in ("e", "E"):
            result += self.consume()  # consume e/E
            if self.current_char() in ("+", "-"):
                result += self.consume()
            while self.current_char() and self.current_char().isdigit():
                result += self.consume()
        
        return result

    def read_ident(self) -> str:
        """Read an identifier."""
        result = ""
        while self.current_char() and (self.current_char().isalnum() or self.current_char() == "_"):
            result += self.consume()
        return result

    def tokenize(self) -> List[Token]:
        """Tokenize the entire input."""
        while self.pos < len(self.text):
            self.skip_whitespace()
            
            if self.pos >= len(self.text):
                break
            
            loc = SourceLoc(self.filename, self.line, self.col)
            ch = self.current_char()
            
            # String literal
            if ch == '"':
                text = self.read_string()
                self.tokens.append(Token(TokenKind.STRING, text, loc))
            
            # Number (may be followed by unit)
            elif ch == "-" or ch.isdigit():
                text = self.read_number()
                self.tokens.append(Token(TokenKind.NUMBER, text, loc))
                
                # Check for unit
                self.skip_whitespace()
                for unit in UNIT_SYMBOLS:
                    if self.text[self.pos:].startswith(unit):
                        if self.pos + len(unit) >= len(self.text) or not self.text[self.pos + len(unit)].isalnum() and self.text[self.pos + len(unit)] != "_":
                            unit_loc = SourceLoc(self.filename, self.line, self.col)
                            self.consume(len(unit))
                            self.tokens.append(Token(TokenKind.UNIT, unit, unit_loc))
                            break
            
            # Version
            elif ch.isdigit() and "." in self.text[self.pos:self.pos+10]:
                text = self.read_number()
                if "." in text:
                    self.tokens.append(Token(TokenKind.VERSION, text, loc))
                else:
                    self.tokens.append(Token(TokenKind.NUMBER, text, loc))
            
            # Identifier or keyword
            elif ch.isalpha() or ch == "_":
                text = self.read_ident()
                if text in KEYWORDS:
                    self.tokens.append(Token(KEYWORDS[text], text, loc))
                else:
                    self.tokens.append(Token(TokenKind.IDENT, text, loc))
            
            # Operators and punctuation
            elif ch == "-" and self.peek_char() == ">":
                self.consume(2)
                self.tokens.append(Token(TokenKind.ARROW, "->", loc))
            elif ch == ".":
                self.consume()
                self.tokens.append(Token(TokenKind.DOT, ".", loc))
            elif ch == ":":
                self.consume()
                self.tokens.append(Token(TokenKind.COLON, ":", loc))
            elif ch == ";":
                self.consume()
                self.tokens.append(Token(TokenKind.SEMICOLON, ";", loc))
            elif ch == "{":
                self.consume()
                self.tokens.append(Token(TokenKind.LBRACE, "{", loc))
            elif ch == "}":
                self.consume()
                self.tokens.append(Token(TokenKind.RBRACE, "}", loc))
            elif ch == "[":
                self.consume()
                self.tokens.append(Token(TokenKind.LBRACKET, "[", loc))
            elif ch == "]":
                self.consume()
                self.tokens.append(Token(TokenKind.RBRACKET, "]", loc))
            elif ch == ",":
                self.consume()
                self.tokens.append(Token(TokenKind.COMMA, ",", loc))
            else:
                # Unknown character
                self.tokens.append(Token(TokenKind.ERROR, ch, loc))
                self.consume()
        
        self.tokens.append(Token(TokenKind.EOF, "", SourceLoc(self.filename, self.line, self.col)))
        return self.tokens
