"""
vte-server: servidor HTTP headless, compatível com a API de chat completions
da OpenAI, embrulhando um único VTEModel.

Existe para hosts externos que rodam backends como subprocessos falando HTTP
em loopback (ex.: Lemonade) -- é o mesmo padrão de isolamento de crash que
vte/core/motor.py já dá para a UI Flet (um VTEModel por processo, falado por
IPC), só trocando o multiprocessing.Pipe por HTTP e o Flet por qualquer
cliente HTTP.

Uso:
    vte-server --gguf-path <path> --port <int> [--host 127.0.0.1]
               [--context-length <int>] [--idle-timeout <segundos>]
               [--vram-limit-pct <pct>] [--parent-pid <pid>]
"""
import argparse
import asyncio
import json
import os
import queue
import signal
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from vte.bridge.errors import VTEError, HIPSafetyError, HIPRuntimeError
from vte.bridge.logger import get_logger
from vte.core.model import VTEModel

logger = get_logger("VTE.Server")


class _ServerState:
    """Guarda o único VTEModel que este processo serve, mais a config lida
    da linha de comando (usada pelos handlers de requisição)."""
    model: VTEModel = None
    model_id: str = "vte"
    load_timestamp: int = 0
    default_max_tokens: int = 512
    # Atualizado no fim de cada geração (streaming e não-streaming) para o
    # endpoint /telemetry: não é recalculado sob demanda porque tok/s só
    # existe de verdade enquanto uma geração roda; entre requisições, o
    # último valor medido é a melhor informação disponível.
    last_decoding_speed_tps: float = 0.0
    # Live counterpart of last_decoding_speed_tps: while a generation is
    # actively producing tokens, /telemetry should show a number that
    # actually moves, not last_decoding_speed_tps sitting frozen at
    # whatever the PREVIOUS generation finished at until this one also
    # finishes. None while idle (distinguishes "no live generation" from
    # "0 tok/s"). live_generation_start is set on the first token of a
    # generation (not before -- prefill has no per-token progress to time),
    # so this is always a decode-only rate, matching the convention
    # `decoding_speed_tps` already uses everywhere else in this file.
    live_generation_start: Optional[float] = None
    live_tokens_generated: int = 0
    # Keyed by (sorted choices tuple, trigger): building a ChoiceConstraint
    # walks the whole vocabulary once (~0.5s measured on a 128K-token
    # tokenizer -- see vte/core/constrained_decoding.py), too slow to pay
    # on every single request in a hot agent loop that sends the same
    # fixed tool-name list every round. Safe to key on choices/trigger
    # alone (not also on the model): this process serves exactly one
    # VTEModel/tokenizer for its whole lifetime -- switching models means
    # a fresh vte-server subprocess (see vte_bridge.py's ensure_server),
    # never a swap in place.
    choice_constraint_cache: dict = {}


state = _ServerState()


def _get_choice_constraint(choices: list, trigger: str):
    from vte.core.constrained_decoding import ChoiceConstraint
    key = (tuple(sorted(choices)), trigger)
    cached = state.choice_constraint_cache.get(key)
    if cached is not None:
        return cached
    constraint = ChoiceConstraint(state.model.tokenizer, choices, trigger=trigger)
    state.choice_constraint_cache[key] = constraint
    return constraint


# --------------------------------------------------------------------------
# Shutdown gracioso e watchdog de processo-pai órfão
#
# Dois mecanismos distintos, cobrindo dois cenários diferentes (ver o plano
# de integração com o Lemonade): (a) SIGINT/SIGBREAK cobre um encerramento
# ORDENADO; (b) o watchdog de PID cobre o cenário em que o processo pai
# (ex.: lemond) morre abruptamente (TerminateProcess no Windows não entrega
# NENHUM sinal capturável ao filho) -- sem isso, o vte-server viraria um
# processo zumbi segurando VRAM indefinidamente.
# --------------------------------------------------------------------------

def _graceful_shutdown():
    if state.model is not None:
        try:
            state.model.unload()
        except Exception as e:
            logger.error(f"Erro ao descarregar modelo durante shutdown: {e}")
        state.model = None


def _install_signal_handlers():
    def _handler(signum, frame):
        logger.info(f"Sinal {signum} recebido -- encerrando graciosamente.")
        _graceful_shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handler)
    sig_break = getattr(signal, "SIGBREAK", None)  # só existe no Windows
    if sig_break is not None:
        signal.signal(sig_break, _handler)


def _parent_process_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            return exit_code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _start_parent_watchdog(parent_pid: int, poll_seconds: float = 5.0):
    def _loop():
        while True:
            time.sleep(poll_seconds)
            if not _parent_process_alive(parent_pid):
                logger.warning(
                    f"Processo pai (PID {parent_pid}) não existe mais -- "
                    f"encerrando e liberando VRAM (watchdog de órfão)."
                )
                _graceful_shutdown()
                os._exit(0)

    threading.Thread(target=_loop, daemon=True, name="VTE-ParentWatchdog").start()


def _check_vram_preflight(vram_limit_pct: float):
    """Heurística de coexistência (v1, a calibrar com medição real -- ver a
    seção "Disciplina de medição" do plano de integração): recusa subir se a
    VRAM já LIVRE (antes de qualquer alocação do VTE) estiver abaixo do
    limite configurado. Não é um teto rígido sobre o que o VTE em si aloca
    (isso exigiria expor VRAM_SAFETY_MARGIN como configurável por instância
    em HIPRuntime, uma mudança maior deixada para depois de medir o
    comportamento real de coexistência) -- é um portão de entrada simples:
    "não tente nem carregar se outro processo já está usando a maior parte
    da VRAM"."""
    from vte.bridge.hip_runtime import HIPRuntime

    probe = HIPRuntime()
    try:
        probe.initialize()
        free_bytes, total_bytes = probe.get_real_mem_info()
    finally:
        probe.cleanup()

    free_pct = (free_bytes / total_bytes) * 100 if total_bytes else 0.0
    logger.info(
        f"VRAM livre antes do load: {free_pct:.1f}% "
        f"({free_bytes / (1024**2):.0f}MB de {total_bytes / (1024**2):.0f}MB)"
    )
    if free_pct < vram_limit_pct:
        raise HIPSafetyError(
            f"VRAM livre atual ({free_pct:.1f}%) está abaixo do limite configurado "
            f"(--vram-limit-pct {vram_limit_pct}%). Recusando carregar para não competir "
            f"por VRAM com outro processo/backend já em uso na GPU."
        )


# --------------------------------------------------------------------------
# Streaming: thread dedicada + fila thread-safe + Event de cancelamento
#
# model.generate() é um generator SÍNCRONO (bloqueante por token) -- e
# generators Python não são thread-safe para fechar (`close()`) de uma
# thread diferente da que os está iterando. Por isso o cancelamento aqui é
# cooperativo (um threading.Event que a própria thread de geração verifica a
# cada token e só ENTÃO chama `close()` nela mesma), nunca uma chamada
# direta de fora. Sem isso, um cliente que desconecta no meio do streaming
# deixaria o VTE gerando tokens em background indefinidamente, gastando
# VRAM/compute e travando a fila de inferência deste processo para o
# próximo request.
# --------------------------------------------------------------------------

_QUEUE_STOP = object()

# --------------------------------------------------------------------------
# Serialização de geração: um único VTEModel neste processo compartilha um
# contexto HIP, um grafo de decode capturado e um KV cache/arena com estado
# mutável (kv_offset, estado do Gated DeltaNet) -- nada disso é reentrante.
# Duas requisições concorrentes (ex.: dois streams abertos ao mesmo tempo)
# chamariam generate() simultaneamente de threads Python diferentes contra o
# MESMO executor/allocator, corrompendo o KV cache ou lançando kernels HIP
# fora de ordem. Este lock torna o vte-server "uma geração de cada vez" por
# processo -- exatamente o nível de isolamento que o Lemonade já assume ao
# tratar cada backend como um único slot de modelo por subprocesso.
# --------------------------------------------------------------------------
_generation_lock = threading.Lock()

_BUSY_RESPONSE = {
    "error": {
        "message": "O VTE já está gerando outra resposta; esta instância processa um pedido por vez.",
        "type": "server_busy",
    },
}


def _run_generation(
    gen, out_queue: "asyncio.Queue", loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event, lock: threading.Lock, stats: dict = None,
):
    """Runs model.generate() in its own OS thread (decode is a real,
    Python-level per-token loop, not just a fire-and-forget GPU kernel), and
    hands each token to the asyncio event loop via call_soon_threadsafe.

    Real perf bug found and fixed here (2026-07): the previous version used
    a plain queue.Queue with the consumer polling `out_queue.get(timeout=0.05)`
    in a tight `while True` loop on the SAME event loop that also owns the
    HTTP connection. That's a synchronous blocking call sitting inside an
    `async def`, waking up 20x/second minimum even with nothing to do, and
    every wake-up (whether it found an item or not) is a GIL handoff this
    thread has to contend with to keep decoding. Measured impact, same
    model/prompt/hardware, isolated one variable at a time: 166.8 tok/s
    in-process, 166.3 tok/s via this same server's non-streaming endpoint
    (no thread, no queue), but only 132.8 tok/s through this streaming path
    with the old polling queue, a real ~20% loss from the consumer thrashing
    the GIL against the generation thread, not from HTTP/network/GPU at all.
    asyncio.Queue lets the consumer `await get()` with zero polling: the
    event loop only wakes up when call_soon_threadsafe actually schedules
    something, so the generation thread stops fighting an idle spin loop
    for GIL time between tokens."""
    try:
        for word in gen:
            # First token starts the live-tps clock (prefill has no
            # per-token progress to time, so timing from before this would
            # count prefill against a "decode speed" figure); every token
            # after that both advances the clock's numerator and gets
            # timed against it. Plain attribute writes on `state`, no lock:
            # CPython's GIL already makes single attribute assignment
            # atomic, and /telemetry only ever reads these, never
            # read-modifies-writes them.
            if state.live_generation_start is None:
                state.live_generation_start = time.perf_counter()
                state.live_tokens_generated = 0
            else:
                state.live_tokens_generated += 1
            loop.call_soon_threadsafe(out_queue.put_nowait, ("chunk", word))
            if stop_event.is_set():
                gen.close()  # mesma thread que itera -- seguro
                break
    except Exception as e:
        loop.call_soon_threadsafe(out_queue.put_nowait, ("error", str(e)))
    finally:
        # `stats` foi preenchido por generate() (por referência) ao exaurir o
        # generator -- carrega completion_tokens pro chunk final de usage.
        loop.call_soon_threadsafe(out_queue.put_nowait, ("done", stats))
        state.live_generation_start = None
        state.live_tokens_generated = 0
        lock.release()


def _openai_chunk(request_id: str, model_name: str, delta: dict, finish_reason=None, usage=None) -> dict:
    chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_name,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if usage is not None:
        chunk["usage"] = usage
    return chunk


def _extract_prompt(body: dict):
    """Extrai o histórico de mensagens (ou prompt cru) de uma requisição no
    formato OpenAI chat/completions. Retorna a lista de mensagens pronta
    para `Tokenizer.apply_chat_template` (que já aceita string única OU
    lista completa -- ver vte/compiler/tokenizer.py::_coerce_chat_messages)."""
    messages = body.get("messages")
    if not messages:
        raise ValueError("Campo 'messages' ausente ou vazio na requisição.")
    return messages


async def health(request: Request) -> JSONResponse:
    ready = state.model is not None
    return JSONResponse({"status": "ready" if ready else "loading"}, status_code=200 if ready else 503)


async def telemetry(request: Request) -> JSONResponse:
    """Real GPU/model telemetry for a status-bar-style display: every
    number here is a live device query (`hipMemGetInfo`) or an actually-
    measured decode speed, not an estimate.

    decoding_speed_tps prefers the LIVE, still-updating rate while a
    generation is actively producing tokens over last_decoding_speed_tps
    (the previous generation's fixed final average) -- a status bar polled
    every few seconds needs a number that visibly moves during a response,
    not one that sits frozen until the whole response finishes. Falls back
    to last_decoding_speed_tps between generations, and to 0.0 within the
    first ~50ms of a fresh generation's first token (one token divided by
    a near-zero elapsed time is noise, not a rate)."""
    if state.model is None or state.model._hip is None:
        return JSONResponse({"status": "loading"}, status_code=503)
    hip = state.model._hip
    free_bytes, total_bytes = hip.get_real_mem_info()
    live_tps = None
    is_generating = state.live_generation_start is not None
    if is_generating:
        elapsed = time.perf_counter() - state.live_generation_start
        if elapsed > 0.05:
            live_tps = state.live_tokens_generated / elapsed
    return JSONResponse({
        "gpu_name": hip.get_gpu_name(),
        "gpu_arch": hip.get_gpu_architecture(),
        "num_cus": hip.get_num_cus(),
        "vram_total_bytes": total_bytes,
        "vram_used_bytes": total_bytes - free_bytes,
        "decoding_speed_tps": live_tps if live_tps is not None else state.last_decoding_speed_tps,
        "is_generating": is_generating,
        "model_id": state.model_id,
    })


async def models_list(request: Request) -> JSONResponse:
    return JSONResponse({
        "object": "list",
        "data": [{
            "id": state.model_id,
            "object": "model",
            "created": state.load_timestamp,
            "owned_by": "vte",
        }],
    })


async def chat_completions(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": {"message": "Corpo da requisição não é um JSON válido.", "type": "invalid_request_error"}}, status_code=400)
    try:
        messages = _extract_prompt(body)
    except ValueError as e:
        return JSONResponse({"error": {"message": str(e), "type": "invalid_request_error"}}, status_code=400)

    # Aceita tanto os nomes OpenAI modernos (max_completion_tokens,
    # repeat_penalty -- o que o Lemonade e clientes OpenAI atuais mandam)
    # quanto os originais do VTE. O adapter C++ do Lemonade também normaliza,
    # mas manter aqui deixa o vte-server correto quando falado direto.
    max_tokens = body.get("max_tokens", body.get("max_completion_tokens", state.default_max_tokens))
    temperature = body.get("temperature")
    top_p = body.get("top_p", 0.9)
    top_k = body.get("top_k", 50)
    repetition_penalty = body.get("repetition_penalty", body.get("repeat_penalty"))
    stream = bool(body.get("stream", False))
    # OpenAI default: the usage-only trailing chunk is opt-in, not automatic.
    include_usage = bool((body.get("stream_options") or {}).get("include_usage", False))
    request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    model_name = body.get("model", "vte")

    # Non-standard OpenAI extension (same idea as vLLM's guided_choice /
    # llama.cpp server's grammar field): when set, forces generation to
    # complete exactly one of `guided_choices` from the moment
    # `guided_choice_trigger` appears in the output stream -- see
    # vte/core/constrained_decoding.py. Optional and additive; a request
    # without it behaves exactly as before this existed.
    guided_choices = body.get("guided_choices")
    choice_constraint = None
    if guided_choices:
        try:
            choice_constraint = _get_choice_constraint(
                guided_choices, body.get("guided_choice_trigger", "```")
            )
        except ValueError as e:
            return JSONResponse({"error": {"message": str(e), "type": "invalid_request_error"}}, status_code=400)

    prompt = state.model.tokenizer.apply_chat_template(messages)
    prompt_tokens = len(state.model.tokenizer.encode(prompt))

    if not stream:
        if not _generation_lock.acquire(blocking=False):
            return JSONResponse(_BUSY_RESPONSE, status_code=429)
        gen_stats: dict = {}
        try:
            text = "".join(
                state.model.generate(
                    prompt, max_tokens=max_tokens, temperature=temperature,
                    top_p=top_p, top_k=top_k, repetition_penalty=repetition_penalty,
                    stats=gen_stats, choice_constraint=choice_constraint,
                )
            )
        except (HIPSafetyError, HIPRuntimeError, VTEError) as e:
            return JSONResponse({"error": {"message": str(e), "type": "server_error"}}, status_code=500)
        except (ValueError, FileNotFoundError) as e:
            return JSONResponse({"error": {"message": str(e), "type": "invalid_request_error"}}, status_code=400)
        finally:
            _generation_lock.release()
        state.last_decoding_speed_tps = gen_stats.get("decoding_speed_tps", 0.0)
        completion_tokens = gen_stats.get("completion_tokens", 0)
        return JSONResponse({
            "id": request_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": gen_stats.get("finish_reason", "stop"),
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "prefill_duration_ttft": gen_stats.get("prefill_duration_ttft", 0.0),
                "decoding_speed_tps": gen_stats.get("decoding_speed_tps", 0.0),
            },
        })

    if not _generation_lock.acquire(blocking=False):
        return JSONResponse(_BUSY_RESPONSE, status_code=429)

    loop = asyncio.get_running_loop()
    out_queue: "asyncio.Queue" = asyncio.Queue()
    stop_event = threading.Event()
    gen_stats: dict = {}
    gen = state.model.generate(
        prompt, max_tokens=max_tokens, temperature=temperature,
        top_p=top_p, top_k=top_k, repetition_penalty=repetition_penalty,
        stats=gen_stats, choice_constraint=choice_constraint,
    )
    gen_thread = threading.Thread(
        target=_run_generation, args=(gen, out_queue, loop, stop_event, _generation_lock, gen_stats), daemon=True,
        name="VTE-GenerationThread",
    )
    gen_thread.start()

    async def sse_stream():
        first = True
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(out_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Nothing to send in the last second, e.g. an unusually
                    # slow decode step; a real chance to notice a client
                    # disconnect without polling every request on a tight
                    # timer the rest of the time (see _run_generation's
                    # docstring for why that tight polling was the actual
                    # ~20% throughput bug).
                    if await request.is_disconnected():
                        stop_event.set()
                    continue
                if kind == "chunk":
                    delta = {"role": "assistant", "content": payload} if first else {"content": payload}
                    first = False
                    yield f"data: {json.dumps(_openai_chunk(request_id, model_name, delta))}\n\n"
                elif kind == "error":
                    yield f"data: {json.dumps({'error': {'message': payload, 'type': 'server_error'}})}\n\n"
                    break
                elif kind == "done":
                    state.last_decoding_speed_tps = (payload or {}).get("decoding_speed_tps", 0.0)
                    finish_reason = (payload or {}).get("finish_reason", "stop")
                    # FastFlowLM-convention timing fields (see generate()'s
                    # stats["prefill_duration_ttft"/"decoding_speed_tps"]), sent
                    # unconditionally on the finish chunk -- Lemonade's telemetry
                    # (StreamingProxy::extract_telemetry_from_chunk) reads them from
                    # any chunk's `usage`, not only the opt-in usage-only one below,
                    # and Lemonade's own VTE requests don't set stream_options.
                    timing_usage = {
                        "prefill_duration_ttft": (payload or {}).get("prefill_duration_ttft", 0.0),
                        "decoding_speed_tps": (payload or {}).get("decoding_speed_tps", 0.0),
                    }
                    yield f"data: {json.dumps(_openai_chunk(request_id, model_name, {}, finish_reason=finish_reason, usage=timing_usage))}\n\n"
                    # Chunk final de usage (convenção OpenAI stream_options.
                    # include_usage): choices vazio + objeto usage, logo antes
                    # do [DONE]. `payload` aqui é o dict stats de _run_generation.
                    # Só emitido se o cliente pediu (default OpenAI é NÃO incluir).
                    if include_usage:
                        completion_tokens = (payload or {}).get("completion_tokens", 0)
                        usage_chunk = {
                            "id": request_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model_name,
                            "choices": [],
                            "usage": {
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens,
                                "total_tokens": prompt_tokens + completion_tokens,
                                **timing_usage,
                            },
                        }
                        yield f"data: {json.dumps(usage_chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                    break
        finally:
            stop_event.set()

    return StreamingResponse(sse_stream(), media_type="text/event-stream")


async def completions(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": {"message": "Corpo da requisição não é um JSON válido.", "type": "invalid_request_error"}}, status_code=400)
    prompt = body.get("prompt")
    if not prompt:
        return JSONResponse({"error": {"message": "Campo 'prompt' ausente.", "type": "invalid_request_error"}}, status_code=400)

    max_tokens = body.get("max_tokens", body.get("max_completion_tokens", state.default_max_tokens))
    temperature = body.get("temperature")
    top_p = body.get("top_p", 0.9)
    top_k = body.get("top_k", 50)
    repetition_penalty = body.get("repetition_penalty", body.get("repeat_penalty"))

    prompt_tokens = len(state.model.tokenizer.encode(prompt))

    if not _generation_lock.acquire(blocking=False):
        return JSONResponse(_BUSY_RESPONSE, status_code=429)
    gen_stats: dict = {}
    try:
        text = "".join(
            state.model.generate(
                prompt, max_tokens=max_tokens, temperature=temperature,
                top_p=top_p, top_k=top_k, repetition_penalty=repetition_penalty,
                stats=gen_stats,
            )
        )
    except (HIPSafetyError, HIPRuntimeError, VTEError) as e:
        return JSONResponse({"error": {"message": str(e), "type": "server_error"}}, status_code=500)
    except (ValueError, FileNotFoundError) as e:
        return JSONResponse({"error": {"message": str(e), "type": "invalid_request_error"}}, status_code=400)
    finally:
        _generation_lock.release()

    state.last_decoding_speed_tps = gen_stats.get("decoding_speed_tps", 0.0)
    completion_tokens = gen_stats.get("completion_tokens", 0)
    return JSONResponse({
        "id": f"cmpl-{uuid.uuid4().hex[:24]}",
        "object": "text_completion",
        "created": int(time.time()),
        "model": body.get("model", "vte"),
        "choices": [{"index": 0, "text": text, "finish_reason": gen_stats.get("finish_reason", "stop")}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "prefill_duration_ttft": gen_stats.get("prefill_duration_ttft", 0.0),
            "decoding_speed_tps": gen_stats.get("decoding_speed_tps", 0.0),
        },
    })


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Rede de segurança final: qualquer exceção que escape dos handlers acima
    # (bug real, tipo inesperado de campo, etc.) não pode vazar um traceback
    # cru pro cliente (potencialmente o próprio Lemonade tentando parsear a
    # resposta como JSON de erro OpenAI) nem derrubar o processo -- Starlette
    # já isola isso por requisição, mas sem este handler a resposta default
    # não segue o formato `{"error": {...}}` que o resto da API usa.
    logger.error(f"Erro não tratado em {request.url.path}: {exc}", exc_info=True)
    return JSONResponse({"error": {"message": "Erro interno do servidor.", "type": "server_error"}}, status_code=500)


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/telemetry", telemetry, methods=["GET"]),
        Route("/v1/models", models_list, methods=["GET"]),
        Route("/v1/chat/completions", chat_completions, methods=["POST"]),
        Route("/v1/completions", completions, methods=["POST"]),
    ],
    exception_handlers={Exception: _unhandled_exception_handler},
)


def _parse_args(argv=None):
    p = argparse.ArgumentParser(prog="vte-server", description=__doc__)
    p.add_argument("--gguf-path", required=True, help="Caminho absoluto do arquivo .gguf a carregar.")
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--context-length", type=int, default=None)
    p.add_argument("--idle-timeout", type=int, default=60,
                   help="Segundos de inatividade antes do unload automático (default: 60, mais curto "
                        "que o padrão de 300s do vte-ui, pensado para uso desktop contínuo). "
                        "0 ou negativo DESABILITA o unload automático -- usado quando um host "
                        "externo (ex.: Lemonade) é dono do ciclo de vida do modelo e não quer "
                        "que o vte-server descarregue por conta própria durante um request longo.")
    p.add_argument("--vram-limit-pct", type=float, default=80.0,
                   help="Heurística de coexistência (ver docstring de _check_vram_preflight): recusa "
                        "carregar se a VRAM livre atual estiver abaixo deste percentual.")
    p.add_argument("--parent-pid", type=int, default=None,
                   help="PID do processo pai (ex.: lemond) -- se fornecido, um watchdog encerra este "
                        "processo e libera a VRAM caso o pai desapareça sem um shutdown limpo.")
    p.add_argument("--templates-dir", default=None,
                   help="Sobrepõe o diretório padrão de templates HIP (vte/compiler/templates/rdna) "
                        "só para este processo. Usado pelo Aetheris Optimizer para subir uma instância "
                        "de teste isolada apontada para um candidato de kernel, sem tocar o vte-server "
                        "de produção nem o diretório de templates oficial.")
    return p.parse_args(argv)


def cli_main():
    args = _parse_args()
    _install_signal_handlers()
    if args.parent_pid is not None:
        _start_parent_watchdog(args.parent_pid)
    if args.templates_dir is not None:
        # Set before any model load: CodegenEngine() call sites across the
        # codebase read this env var once, at construction, with no argument
        # threading needed at any of those call sites.
        os.environ["VTE_TEMPLATES_DIR"] = str(Path(args.templates_dir).resolve())

    # Falha rápida e legível: um host como o Lemonade spawna este processo e
    # faz polling em /health esperando "ready" -- se o load falhar (VRAM
    # insuficiente, GGUF corrompido, arquitetura não suportada), deixar a
    # exceção subir crua faria o processo morrer com um traceback Python no
    # stderr em vez de um log claro, e ainda assim o host ficaria fazendo
    # polling até estourar o próprio timeout dele. Aqui o processo morre
    # IMEDIATAMENTE (exit code 1) com uma linha de log objetiva, para o host
    # detectar a falha de carregamento o quanto antes.
    try:
        _check_vram_preflight(args.vram_limit_pct)
        logger.info(f"Carregando {args.gguf_path}...")
        state.model = VTEModel.from_path(
            args.gguf_path,
            context_length=args.context_length,
            idle_timeout_seconds=args.idle_timeout,
            enable_auto_unload=(args.idle_timeout > 0),
        )
    except Exception as e:
        logger.error(f"Falha ao carregar o modelo, encerrando: {e}")
        sys.exit(1)

    state.model_id = Path(args.gguf_path).stem
    state.load_timestamp = int(time.time())
    logger.info(f"Modelo carregado. Servindo em http://{args.host}:{args.port}")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    cli_main()
