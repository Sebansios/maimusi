"""Frozen entry point of the engine service (see hangul_ime/ime_service.py).

With --pipe (Windows) it serves many input-method clients over a named pipe
(hangul_ime/pipe_service.py); otherwise it speaks over stdin/stdout.
"""
import sys

if "--pipe" in sys.argv[1:]:
    from hangul_ime.pipe_service import main
    raise SystemExit(main(sys.argv[1:]))

from hangul_ime.ime_service import main

raise SystemExit(main())
