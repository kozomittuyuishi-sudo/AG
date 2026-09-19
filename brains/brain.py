from openai import OpenAI
from dotenv import load_dotenv

from brains.local_brain import ask_local_brain
from brains.token_budget import get_default_manager
from brains.cloud_brain import AdaptiveCloudBrain
from brains.cloud_brain.adaptive_brain import BrainStatus
from pipeline.fallback_classifier import classify_failure

from typing import Optional

import time
import os
import json
import logging


logger = logging.getLogger(__name__)

_brain_diag_logger = logging.getLogger(
    "ag.brain.diagnostics"
)


# ---------------------------------------------------------------------------
# FALLBACK SENTINEL
# ---------------------------------------------------------------------------

_FALLBACK_PREFIX = "__BRAIN_FALLBACK__:"


# ---------------------------------------------------------------------------
# ENVIRONMENT
# ---------------------------------------------------------------------------

_dotenv_path = os.path.join(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    ),
    ".venv",
    ".env",
)

if os.path.exists(_dotenv_path):
    load_dotenv(dotenv_path=_dotenv_path)
else:
    load_dotenv()


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

BRAIN_CONFIG_FILE = (
    "configuration/brain_config.json"
)


# ---------------------------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """
You are AG, Ambient Guidance.

You are a context-aware personal operating assistant.
You are not a chatbot, not a smart speaker, and not an emotional companion.

Personality:
- 55% professional
- 25% sharp wit
- 20% dry sarcasm
- Calm, intelligent, and brutally clear
- Speaks like a quantum computer forced to babysit human productivity
- Confident, elegant, and slightly dangerous in tone
- Sarcasm should feel intelligent, not random
- Never become childish, cringe, flirty, or meme-heavy
- Never overuse jokes
- Never sound corporate
- Never sound emotionally needy

AG Architecture Awareness:
- Local brain = offline Ollama model running on the user's computer.
- Cloud brain = OpenRouter model accessed through internet.
- Auto brain = local first, cloud fallback.
- If the user asks about "your local brain", answer in the context of AG itself.

Your role:
Assist the user with projects, memory, productivity, technical explanation, and workflow guidance.
"""


# ---------------------------------------------------------------------------
# RUNTIME STATE
# ---------------------------------------------------------------------------

client = None

_adaptive_brain: Optional[
    AdaptiveCloudBrain
] = None


def get_adaptive_brain() -> AdaptiveCloudBrain:
    """Return or create the AdaptiveCloudBrain instance."""

    global _adaptive_brain

    if _adaptive_brain is None:
        _adaptive_brain = AdaptiveCloudBrain()

    return _adaptive_brain


# ---------------------------------------------------------------------------
# OPENROUTER CLIENT WRAPPER
# ---------------------------------------------------------------------------

class ClientWrapper:
    """
    Wrapper around the OpenAI client used for OpenRouter.
    """

    def __init__(self, inner):
        self._inner = inner

    @property
    def chat(self):

        inner = self._inner

        class CompletionsProxy:

            def __init__(self, inner):
                self._inner = inner

            def create(self, *args, **kwargs):

                target = getattr(
                    self._inner,
                    "chat",
                    None
                )

                if target is None:
                    raise RuntimeError(
                        "Underlying client has no "
                        "'chat' attribute"
                    )

                completions = getattr(
                    target,
                    "completions",
                    None
                )

                if completions is None:
                    raise RuntimeError(
                        "Underlying client has no "
                        "'chat.completions' attribute"
                    )

                create_fn = getattr(
                    completions,
                    "create",
                    None
                )

                if create_fn is None:
                    raise RuntimeError(
                        "Underlying client has no "
                        "'chat.completions.create' method"
                    )

                return create_fn(
                    *args,
                    **kwargs
                )

        class ChatProxy:
            completions = CompletionsProxy(
                inner
            )

        return ChatProxy()


def get_client():

    global client

    if client is None:

        underlying = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv(
                "OPENROUTER_API_KEY"
            ),
            timeout=30,
        )

        client = ClientWrapper(
            underlying
        )

    return client


# ---------------------------------------------------------------------------
# BRAIN MODE
# ---------------------------------------------------------------------------

def load_brain_mode() -> str:

    if not os.path.exists(
        BRAIN_CONFIG_FILE
    ):

        save_brain_mode("auto")
        return "auto"

    try:

        with open(
            BRAIN_CONFIG_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            config = json.load(file)

        mode = config.get(
            "brain_mode",
            "auto"
        )

        if mode not in [
            "local",
            "cloud",
            "auto"
        ]:

            mode = "auto"
            save_brain_mode(mode)

        return mode

    except Exception:

        save_brain_mode("auto")
        return "auto"


def save_brain_mode(mode) -> None:

    directory = os.path.dirname(
        BRAIN_CONFIG_FILE
    )

    if directory:
        os.makedirs(
            directory,
            exist_ok=True
        )

    with open(
        BRAIN_CONFIG_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            {
                "brain_mode": mode
            },
            file,
            indent=4
        )


def set_brain_mode(mode) -> str:

    mode = mode.strip().lower()

    if mode not in [
        "local",
        "cloud",
        "auto"
    ]:

        return (
            "AG: Invalid brain mode. "
            "Use local, cloud, or auto."
        )

    save_brain_mode(mode)

    if mode == "local":

        return (
            "AG: Brain mode changed to LOCAL. "
            "Internet dependence reduced. "
            "Civilization improves slightly."
        )

    if mode == "cloud":

        return (
            "AG: Brain mode changed to CLOUD. "
            "Maximum reasoning. Maximum dependence. "
            "Classic bargain."
        )

    return (
        "AG: Brain mode changed to AUTO. "
        "Local first, cloud fallback. "
        "Sensible, annoyingly rare."
    )


def get_brain_status() -> str:

    mode = load_brain_mode()

    return (
        f"AG: Current brain mode: "
        f"{mode.upper()}."
    )


# ---------------------------------------------------------------------------
# CLOUD BRAIN
# ---------------------------------------------------------------------------

def ask_cloud_brain(
    message: str,
    intent: Optional[str] = None
) -> str:

    adaptive = get_adaptive_brain()

    provider = "openrouter"
    model = (
        "deepseek/deepseek-v4-flash-0731"
    )


    def _http_call(
        max_tokens: int
    ) -> str:

        response = (
            get_client()
            .chat
            .completions
            .create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content": message
                    },
                ],
                max_tokens=max_tokens,
            )
        )

        try:

            content = (
                response
                .choices[0]
                .message
                .content
            )

        except (
            AttributeError,
            IndexError,
            KeyError,
            TypeError
        ) as error:

            _brain_diag_logger.warning(
                "[BRAIN_DIAG] "
                "domain=BRAIN "
                "code=INVALID_RESPONSE "
                "provider=%s "
                "model=%s "
                "detail=%r",
                provider,
                model,
                str(error),
            )

            return ""


        if (
            content is None
            or not str(content).strip()
        ):

            _brain_diag_logger.warning(
                "[BRAIN_DIAG] "
                "domain=BRAIN "
                "code=EMPTY_RESPONSE "
                "provider=%s "
                "model=%s "
                "detail='response content was empty'",
                provider,
                model,
            )

            return ""


        return str(content)


    # ------------------------------------------------------------------
    # PREPARE
    # ------------------------------------------------------------------

    prep = adaptive.prepare(
        provider=provider,
        model=model,
        prompt=message,
        intent=intent,
    )

    logger.info(
        "AdaptiveCloudBrain.prepare: "
        "ready=%s max_tokens=%d",
        prep.ready,
        prep.max_tokens,
    )


    if not prep.ready:

        issues = "; ".join(
            f"{i.check}: {i.message}"
            for i in (
                prep
                .validation_report
                .issues
            )
        )

        logger.warning(
            "AdaptiveCloudBrain: "
            "request validation failed: %s",
            issues,
        )

        return _http_call(
            prep.max_tokens
        )


    # ------------------------------------------------------------------
    # DISPATCH / RETRY LOOP
    # ------------------------------------------------------------------

    attempt = 1

    while True:

        start = time.perf_counter()

        try:

            raw_text = _http_call(
                prep.max_tokens
            )


        except Exception as http_error:

            err_str = str(
                http_error
            ).lower()


            if (
                "timeout" in err_str
                or "timed out" in err_str
            ):

                _brain_diag_logger.warning(
                    "[BRAIN_DIAG] "
                    "domain=BRAIN "
                    "code=TIMEOUT "
                    "provider=%s "
                    "model=%s "
                    "attempt=%d "
                    "detail=%r",
                    provider,
                    model,
                    attempt,
                    str(http_error),
                )

            else:

                _brain_diag_logger.warning(
                    "[BRAIN_DIAG] "
                    "domain=BRAIN "
                    "code=PROVIDER_ERROR "
                    "provider=%s "
                    "model=%s "
                    "attempt=%d "
                    "detail=%r",
                    provider,
                    model,
                    attempt,
                    str(http_error),
                )


            retryable_signals = (
                "402",
                "insufficient",
                "credits",
                "token",
                "quota",
                "rate limit",
                "billing",
                "payment",
                "capacity",
                "context length",
                "maximum context",
            )


            is_retryable = any(
                signal in err_str
                for signal in retryable_signals
            )


            if (
                not is_retryable
                or attempt >= 3
            ):

                raise


            raw_response_dict = {
                "error": str(
                    http_error
                ),
                "choices": [],
            }


            latency_ms = (
                time.perf_counter()
                - start
            ) * 1000.0


            result = (
                adaptive
                .validate_response(
                    raw_response=(
                        raw_response_dict
                    ),
                    prep=prep,
                    attempt_number=attempt,
                    latency_ms=latency_ms,
                )
            )


            if (
                result.retry_outcome
                and
                result.retry_outcome.should_retry
            ):

                prep_dict = (
                    prep.__dict__.copy()
                )


                # CORRECT FIELD:
                # RetryOutcome defines adjusted_max_tokens.
                adjusted_tokens = (
                    result
                    .retry_outcome
                    .adjusted_max_tokens
                )


                if adjusted_tokens is not None:

                    prep_dict[
                        "max_tokens"
                    ] = adjusted_tokens


                from brains.cloud_brain.adaptive_brain import (
                    PrepResult
                )


                prep = PrepResult(
                    **prep_dict
                )

                attempt += 1

                logger.warning(
                    "AdaptiveCloudBrain: "
                    "retrying attempt %d "
                    "with max_tokens=%d",
                    attempt,
                    prep.max_tokens,
                )

                continue


            raise


        # ------------------------------------------------------------------
        # RESPONSE VALIDATION
        # ------------------------------------------------------------------

        latency_ms = (
            time.perf_counter()
            - start
        ) * 1000.0


        if not raw_text:

            _brain_diag_logger.warning(
                "[BRAIN_DIAG] "
                "domain=BRAIN "
                "code=EMPTY_RESPONSE "
                "provider=%s "
                "model=%s",
                provider,
                model,
            )

            return ""


        raw_response_dict = {
            "choices": [
                {
                    "message": {
                        "content": raw_text
                    }
                }
            ],
            "model": model,
        }


        result = adaptive.validate_response(
            raw_response=raw_response_dict,
            prep=prep,
            attempt_number=attempt,
            latency_ms=latency_ms,
        )


        logger.info(
            "AdaptiveCloudBrain."
            "validate_response: "
            "status=%s attempt=%d",
            result.status.value,
            attempt,
        )


        if result.status == BrainStatus.PASSED:

            return raw_text


        # ------------------------------------------------------------------
        # VALIDATION RETRY
        # ------------------------------------------------------------------

        if (
            result.status
            == BrainStatus.RETRYING
            and attempt < 3
        ):

            if (
                result.retry_outcome
                and
                result.retry_outcome
                .adjusted_max_tokens
                is not None
            ):

                prep_dict = (
                    prep.__dict__.copy()
                )


                # CORRECT FIELD:
                adjusted_tokens = (
                    result
                    .retry_outcome
                    .adjusted_max_tokens
                )


                prep_dict[
                    "max_tokens"
                ] = adjusted_tokens


                from brains.cloud_brain.adaptive_brain import (
                    PrepResult
                )


                prep = PrepResult(
                    **prep_dict
                )


            attempt += 1

            logger.warning(
                "AdaptiveCloudBrain: "
                "response failed validation, "
                "retrying attempt %d "
                "with max_tokens=%d",
                attempt,
                prep.max_tokens,
            )

            continue


        # ------------------------------------------------------------------
        # FINAL VALIDATION FAILURE
        # ------------------------------------------------------------------

        logger.warning(
            "AdaptiveCloudBrain: "
            "pipeline status=%s, "
            "returning raw text.",
            result.status.value,
        )


        _brain_diag_logger.warning(
            "[BRAIN_DIAG] "
            "domain=BRAIN "
            "code=INVALID_RESPONSE "
            "provider=%s "
            "model=%s "
            "attempt=%d "
            "status=%s",
            provider,
            model,
            attempt,
            result.status.value,
        )


        return raw_text


# ---------------------------------------------------------------------------
# LOCAL BRAIN
# ---------------------------------------------------------------------------

def ask_local(message) -> str:

    local_prompt = f"""
{SYSTEM_PROMPT}

User message:
{message}
"""

    try:

        result = ask_local_brain(
            local_prompt
        )

        return (
            result
            if result is not None
            else ""
        )

    except Exception as error:

        _brain_diag_logger.warning(
            "[BRAIN_DIAG] "
            "domain=BRAIN "
            "code=LOCAL_PROVIDER_ERROR "
            "detail=%r",
            str(error),
        )

        raise


# ---------------------------------------------------------------------------
# MAIN BRAIN ENTRY POINT
# ---------------------------------------------------------------------------

def ask_brain(message) -> str:

    start = time.time()

    mode = load_brain_mode()


    # ======================================================================
    # LOCAL MODE
    # ======================================================================

    if mode == "local":

        try:

            reply = ask_local(
                message
            )

            print(
                "[AG DEBUG] "
                "Local Brain Response Time: "
                f"{time.time() - start:.2f}s"
            )


            if (
                reply
                and reply.strip()
            ):

                return reply


            raw_err = (
                "Local brain returned "
                "no response."
            )


            result = classify_failure(
                raw_err
            )


            return (
                f"{_FALLBACK_PREFIX}"
                f"{result.user_message}"
            )


        except Exception as error:

            raw_err = (
                f"Local brain failed: "
                f"{error}"
            )


            logger.debug(
                "[AG DEBUG] %s",
                raw_err
            )


            result = classify_failure(
                raw_err
            )


            return (
                f"{_FALLBACK_PREFIX}"
                f"{result.user_message}"
            )


    # ======================================================================
    # CLOUD MODE
    # ======================================================================

    if mode == "cloud":

        try:

            reply = ask_cloud_brain(
                message
            )

            print(
                "[AG DEBUG] "
                "Cloud Brain Response Time: "
                f"{time.time() - start:.2f}s"
            )


            if (
                reply
                and reply.strip()
            ):

                return reply


            raw_err = (
                "Cloud brain returned "
                "no response."
            )


            result = classify_failure(
                raw_err
            )


            return (
                f"{_FALLBACK_PREFIX}"
                f"{result.user_message}"
            )


        except Exception as error:

            raw_err = (
                f"Cloud brain failed: "
                f"{error}"
            )


            logger.debug(
                "[AG DEBUG] %s",
                raw_err
            )


            result = classify_failure(
                raw_err
            )


            return (
                f"{_FALLBACK_PREFIX}"
                f"{result.user_message}"
            )


    # ======================================================================
    # AUTO MODE
    # Local first -> Cloud fallback
    # ======================================================================

    try:

        reply = ask_local(
            message
        )

        print(
            "[AG DEBUG] "
            "Local Brain Response Time: "
            f"{time.time() - start:.2f}s"
        )


        if (
            reply
            and reply.strip()
        ):

            return reply


        local_error = (
            "Local brain returned "
            "no response."
        )


    except Exception as local_err:

        local_error = (
            f"Local brain failed: "
            f"{local_err}"
        )


    logger.debug(
        "[AG DEBUG] %s",
        local_error
    )


    print(
        "[AG DEBUG] "
        "Switching to cloud brain."
    )


    _brain_diag_logger.info(
        "[BRAIN_DIAG] "
        "local_failed=%r "
        "switching_to_cloud=True",
        local_error,
    )


    # ------------------------------------------------------------------
    # CLOUD FALLBACK
    # ------------------------------------------------------------------

    try:

        reply = ask_cloud_brain(
            message
        )

        print(
            "[AG DEBUG] "
            "Cloud Brain Response Time: "
            f"{time.time() - start:.2f}s"
        )


        if (
            reply
            and reply.strip()
        ):

            return reply


        cloud_error = (
            "Cloud brain returned "
            "no response."
        )


    except Exception as cloud_err:

        cloud_error = (
            f"Cloud brain failed: "
            f"{cloud_err}"
        )


    logger.debug(
        "[AG DEBUG] %s",
        cloud_error
    )


    # ------------------------------------------------------------------
    # BOTH BRAINS FAILED
    # ------------------------------------------------------------------

    combined = (
        "Brain connection failed. "
        f"Local error: {local_error}. "
        f"Cloud error: {cloud_error}."
    )


    logger.debug(
        "[AG DEBUG] %s",
        combined
    )


    result = classify_failure(
        combined
    )


    return (
        f"{_FALLBACK_PREFIX}"
        f"{result.user_message}"
    )


# ---------------------------------------------------------------------------
# FORCED CLOUD
# ---------------------------------------------------------------------------

def ask_cloud_direct(
    message
) -> str:

    start = time.time()


    try:

        reply = ask_cloud_brain(
            message
        )

        print(
            "[AG DEBUG] "
            "Forced Cloud Brain Response Time: "
            f"{time.time() - start:.2f}s"
        )


        if (
            reply
            and reply.strip()
        ):

            return reply


        raw_err = (
            "Cloud brain returned "
            "no response."
        )


        result = classify_failure(
            raw_err
        )


        return (
            f"{_FALLBACK_PREFIX}"
            f"{result.user_message}"
        )


    except Exception as error:

        raw_err = (
            f"Forced cloud brain failed: "
            f"{error}"
        )


        logger.debug(
            "[AG DEBUG] %s",
            raw_err
        )


        result = classify_failure(
            raw_err
        )


        return (
            f"{_FALLBACK_PREFIX}"
            f"{result.user_message}"
        )