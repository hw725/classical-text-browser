"""고전한문 자동 표점 마이크로서비스.

본체(classical-text-browser)에서 HTTP로 호출하는 별도 프로세스.
torch/transformers 같은 무거운 의존성을 본체에서 격리하기 위해 분리되었다.
"""

__version__ = "0.1.0"
