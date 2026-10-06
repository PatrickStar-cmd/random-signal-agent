"""Cloud-deployable conversational agent for random signal analysis."""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import wave
from dataclasses import dataclass, field
from contextvars import ContextVar
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from .acquisition import (
    AcquisitionPlan,
    acquire_with_plan,
    build_acquisition_plan,
    list_acquisition_channels,
    load_signal_file,
)
from .advanced_analysis import AdvancedAnalysisConfig, advanced_random_process_analysis
from .analysis import summarize_signal_window
from .preprocessing import (
    PREPROCESS_METHODS,
    PreprocessConfig,
    list_preprocess_methods,
    normalize_preprocess_method,
    preprocess_signal,
)
from .signal_processing import (
    PreprocessResult,
    SignalBundle,
    SignalConfig,
    decimate_for_export,
    estimate_snr,
    extract_frequency_features,
    extract_time_features,
)
from .llm_client import LLMClientError, OpenAICompatibleClient
from .model_settings import session_model
from .tasks import emit_progress, check_cancelled
from .limits import LIMITS


AUDIO_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "audio"


@dataclass
class ConversationState:
    """State held by one chat session."""

    session_id: str
    bundle: SignalBundle | None = None
    processed: Any | None = None
    summary: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    preprocess_results: dict[str, Any] = field(default_factory=dict)
    preprocess_comparison: dict[str, Any] | None = None
    pending_preprocess_request: str | None = None
    messages: list[dict[str, str]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    last_uploaded_path: str | None = None
    tool_library: dict[str, dict[str, Any]] = field(default_factory=dict)
    random_process_library: dict[str, dict[str, Any]] = field(default_factory=dict)
    acquisition_plan: dict[str, Any] | None = None
    acquisition_history: list[dict[str, Any]] = field(default_factory=list)
    audio_result: dict[str, Any] | None = None
    last_knowledge_topic: str | None = None
    last_knowledge_question: str | None = None
    last_intent: str | None = None
    comparison_goal: str = "waveform"
    diagnostic_lab: dict[str, Any] = field(default_factory=dict)


class RandomSignalDialogueAgent:
    """A tool-using conversational agent for random signal workflows."""

    def __init__(self) -> None:
        self.sessions: dict[str, ConversationState] = {}
        self._model_context = ContextVar(f'model-client-{id(self)}', default=None)
        self.llm = OpenAICompatibleClient.from_env()

    @property
    def llm(self):
        return self._model_context.get() or self._default_llm

    @llm.setter
    def llm(self,value):
        self._default_llm = value

    def get_session(self, session_id: str) -> ConversationState:
        """Get or create a conversation session."""
        if session_id not in self.sessions:
            self.sessions[session_id] = ConversationState(session_id=session_id)
        return self.sessions[session_id]

    @session_model
    def chat(
        self,
        session_id: str,
        message: str,
        tool_library: dict[str, Any] | None = None,
        agent_mode: bool = False,
    ) -> dict[str, Any]:
        """Handle a user message and call the appropriate signal tools."""
        state = self.get_session(session_id)
        self._update_tool_library(state, tool_library)
        text = message.strip()
        state.messages.append({"role": "user", "content": text})
        if any(phrase in text.lower() for phrase in ('诊断信号','诊断当前','检测故障','分析异常','diagnose signal')):
            from .diagnostics import diagnose_state
            diagnostic = diagnose_state(state)
            calls = [{"tool":"diagnose_signal","status":"success","event_count":len(diagnostic['events'])}]
            state.tool_calls.extend(calls)
            facts = '\n'.join(f"- {e['label']}：{e['start']:.3g}–{e['end']:.3g} 秒。{e['alternatives']}" for e in diagnostic['events'][:8])
            reply = f"已完成观测信号诊断，发现 {len(diagnostic['events'])} 个候选事件。\n{facts or '当前阈值下没有发现候选事件。'}\n可在诊断实验室查看时频证据并运行验证实验；检测结果不构成故障定论。"
            state.messages.append({"role":"assistant","content":reply})
            return {"reply":reply,"state":self.serialize_state(state),"tool_calls":calls}
        turn_tool_calls: list[dict[str, Any]] = []
        intent = self._route_intent(state, text)

        if intent == "out_of_scope":
            answer = self._out_of_scope_message()
            state.messages.append({"role": "assistant", "content": answer})
            state.last_intent = intent
            return {
                "reply": answer,
                "state": self.serialize_state(state),
                "intent": intent,
                "tool_calls": turn_tool_calls,
            }

        if intent == "external_general":
            answer = self._call_external_general_api(turn_tool_calls, text)
            state.messages.append({"role": "assistant", "content": answer})
            state.tool_calls.extend(turn_tool_calls)
            state.last_intent = intent
            return {
                "reply": answer,
                "state": self.serialize_state(state),
                "intent": intent,
                "tool_calls": turn_tool_calls,
            }

        if intent == "knowledge":
            answer = self._answer_signal_knowledge(state, text)
            state.messages.append({"role": "assistant", "content": answer})
            state.last_intent = intent
            return {
                "reply": answer,
                "state": self.serialize_state(state),
                "intent": intent,
                "tool_calls": turn_tool_calls,
            }

        if agent_mode and intent in {"acquire", "stop_realtime"}:
            answer, intent = self._chat_locally(state, text, turn_tool_calls, agent_mode=True)
            state.messages.append({"role": "assistant", "content": answer})
            state.tool_calls.extend(turn_tool_calls)
            state.last_intent = intent
            return {
                "reply": answer,
                "state": self.serialize_state(state),
                "intent": intent,
                "tool_calls": turn_tool_calls,
            }

        if self.llm.configured:
            try:
                answer, intent = self._chat_with_model_tools(state, text, turn_tool_calls, intent)
            except Exception:
                answer, intent = self._chat_locally(state, text, turn_tool_calls, agent_mode=agent_mode)
                answer = self._polish_local_answer(state, text, answer)
        else:
            answer, intent = self._chat_locally(state, text, turn_tool_calls, agent_mode=agent_mode)

        state.messages.append({"role": "assistant", "content": answer})
        state.tool_calls.extend(turn_tool_calls)
        state.last_intent = intent
        return {
            "reply": answer,
            "state": self.serialize_state(state),
            "intent": intent,
            "tool_calls": turn_tool_calls,
        }

    @session_model
    def chat_stream(
        self,
        session_id: str,
        message: str,
        tool_library: dict[str, Any] | None = None,
        agent_mode: bool = False,
    ) -> Any:
        """Yield chat response events, streaming the final LLM answer when possible."""

        state = self.get_session(session_id)
        self._update_tool_library(state, tool_library)
        text = message.strip()
        state.messages.append({"role": "user", "content": text})
        turn_tool_calls: list[dict[str, Any]] = []
        answer_parts: list[str] = []
        intent = (
            "preprocess"
            if state.pending_preprocess_request and self._looks_like_preprocess_selection(text)
            else self._detect_intent(text)
        )
        intent = self._route_intent(state, text, intent)

        if intent == "out_of_scope":
            answer = self._out_of_scope_message()
            yield {"event": "delta", "delta": answer}
            state.messages.append({"role": "assistant", "content": answer})
            state.last_intent = intent
            yield {
                "event": "done",
                "reply": answer,
                "state": self.serialize_state(state),
                "intent": intent,
                "tool_calls": turn_tool_calls,
            }
            return

        if intent == "external_general":
            answer = self._call_external_general_api(turn_tool_calls, text)
            for call in turn_tool_calls:
                yield {
                    "event": "tool_call",
                    "tool_call": call,
                    "state": self.serialize_state(state),
                }
            yield {"event": "delta", "delta": answer}
            state.messages.append({"role": "assistant", "content": answer})
            state.tool_calls.extend(turn_tool_calls)
            state.last_intent = intent
            yield {
                "event": "done",
                "reply": answer,
                "state": self.serialize_state(state),
                "intent": intent,
                "tool_calls": turn_tool_calls,
            }
            return

        if intent == "knowledge":
            answer = self._answer_signal_knowledge(state, text)
            yield {"event": "delta", "delta": answer}
            state.messages.append({"role": "assistant", "content": answer})
            state.last_intent = intent
            yield {
                "event": "done",
                "reply": answer,
                "state": self.serialize_state(state),
                "intent": intent,
                "tool_calls": turn_tool_calls,
            }
            return

        if agent_mode and intent in {"acquire", "stop_realtime"}:
            answer, intent = self._chat_locally(state, text, turn_tool_calls, agent_mode=True)
            for call in turn_tool_calls:
                yield {
                    "event": "tool_call",
                    "tool_call": call,
                    "state": self.serialize_state(state),
                }
            yield {"event": "delta", "delta": answer}
            state.messages.append({"role": "assistant", "content": answer.strip()})
            state.tool_calls.extend(turn_tool_calls)
            state.last_intent = intent
            yield {
                "event": "done",
                "reply": answer.strip(),
                "state": self.serialize_state(state),
                "intent": intent,
                "tool_calls": turn_tool_calls,
            }
            return

        if self._should_handle_locally(intent, text):
            answer, intent = self._chat_locally(state, text, turn_tool_calls, agent_mode=agent_mode)
            answer_parts = [answer]
            for call in turn_tool_calls:
                yield {
                    "event": "tool_call",
                    "tool_call": call,
                    "state": self.serialize_state(state),
                }
            yield {"event": "delta", "delta": answer}
            state.messages.append({"role": "assistant", "content": answer.strip()})
            state.tool_calls.extend(turn_tool_calls)
            state.last_intent = intent
            yield {
                "event": "done",
                "reply": answer.strip(),
                "state": self.serialize_state(state),
                "intent": intent,
                "tool_calls": turn_tool_calls,
            }
            return

        if self.llm.configured:
            try:
                final_messages, direct_answer, intent = self._prepare_model_tool_response(
                    state,
                    text,
                    turn_tool_calls,
                    intent,
                )
                for call in turn_tool_calls:
                    yield {
                        "event": "tool_call",
                        "tool_call": call,
                        "state": self.serialize_state(state),
                    }
                if final_messages is not None:
                    answer = self._local_final_answer(state, text)
                    answer_parts = [answer]
                    yield {"event": "delta", "delta": answer}
                else:
                    answer = direct_answer or self._fallback(state)
                    answer_parts.append(answer)
                    yield {"event": "delta", "delta": answer}
            except Exception:
                answer, intent = self._chat_locally(state, text, turn_tool_calls, agent_mode=agent_mode)
                answer = self._polish_local_answer(state, text, answer)
                answer_parts = [answer]
                yield {"event": "delta", "delta": answer}
        else:
            answer, intent = self._chat_locally(state, text, turn_tool_calls, agent_mode=agent_mode)
            answer_parts = [answer]
            yield {"event": "delta", "delta": answer}

        state.messages.append({"role": "assistant", "content": "".join(answer_parts).strip()})
        state.tool_calls.extend(turn_tool_calls)
        state.last_intent = intent
        yield {
            "event": "done",
            "reply": "".join(answer_parts).strip(),
            "state": self.serialize_state(state),
            "intent": intent,
            "tool_calls": turn_tool_calls,
        }

    def _should_handle_locally(self, intent: str, text: str) -> bool:
        return intent in {"acquire", "preprocess", "analyze", "stop_realtime"}

    def _route_intent(
        self,
        state: ConversationState,
        text: str,
        intent: str | None = None,
    ) -> str:
        detected = intent or (
            "preprocess"
            if state.pending_preprocess_request and self._looks_like_preprocess_selection(text)
            else self._detect_intent(text)
        )
        if self._requests_external_general_answer(text):
            return "external_general"
        if detected == "explain" and self._looks_like_knowledge_formula_request(state, text):
            return "knowledge"
        if self._looks_like_knowledge_question(text) and not self._looks_like_current_signal_request(text):
            return "knowledge"
        if self._looks_like_knowledge_followup(state, text, detected):
            return "knowledge"
        if detected == "analyze" and state.bundle is None and self._looks_like_knowledge_question(text):
            return "knowledge"
        if detected == "unknown" and self._is_random_signal_related(text):
            return "knowledge"
        if detected == "unknown" and not self._is_random_signal_related(text):
            return "out_of_scope"
        return detected

    def _requests_external_general_answer(self, text: str) -> bool:
        lowered = text.lower()
        triggers = [
            "调用外部api", "调用外部 api", "用外部api", "用外部 api",
            "外部api回答", "外部 api回答", "让外部api回答", "让外部 api回答",
            "通用问答", "开放问答", "general answer", "external api",
        ]
        return any(trigger in lowered for trigger in triggers)

    def _is_random_signal_related(self, text: str) -> bool:
        lowered = text.lower()
        keywords = [
            "随机信号", "随机过程", "信号", "采样", "采集", "噪声", "干扰", "高斯", "白噪声",
            "均匀噪声", "脉冲", "ar", "自回归", "卡尔曼", "滤波", "预处理", "去噪",
            "时域", "频域", "频谱", "功率谱", "fft", "主频", "谱熵", "自相关", "互相关",
            "正弦", "方波", "三角波", "锯齿波", "线性调频", "chirp", "sine", "square",
            "rms", "snr", "均方根", "峰值", "峭度", "偏度", "matlab", "自主采集", "自动采集",
            "自动巡检", "多通道", "多渠道", "多源", "实时采集", "流式", "传感器", "网关",
            "acquire", "collect", "autonomous", "multi-channel", "multichannel",
        ]
        return any(keyword in lowered for keyword in keywords)

    def _looks_like_knowledge_question(self, text: str) -> bool:
        lowered = text.lower()
        question_words = [
            "是什么", "什么是", "什么意思", "含义", "原理", "区别", "为什么", "怎么理解",
            "介绍", "解释", "解释一下", "说明", "说明一下", "知识点", "概念", "公式", "定义", "作用",
            "怎么用", "有什么用",
            "是不是", "是否", "算不算", "能不能", "可不可以", "属于", "算是", "吗",
        ]
        return self._is_random_signal_related(text) and any(word in lowered for word in question_words)

    def _looks_like_current_signal_request(self, text: str) -> bool:
        lowered = text.lower()
        direct_commands = [
            "分析当前", "分析这个", "分析这段", "解释当前结果", "解释这个结果", "解释这段结果",
            "看当前", "判断当前", "评价当前", "对当前信号做", "对当前结果做", "对这个信号做",
            "对这段信号做", "当前信号做", "当前结果做",
        ]
        if any(word in lowered for word in direct_commands):
            return True
        current_context = any(
            word in lowered
            for word in [
                "当前信号", "当前图", "当前结果", "当前这段", "这个信号", "这段信号", "这条曲线",
                "我的信号", "刚才的信号", "上面的信号", "图中信号", "图里信号", "处理后信号",
                "预处理后信号", "降噪后信号",
            ]
        )
        action_words = [
            "分析", "计算", "输出", "给出", "求", "估计", "拟合", "建模", "做",
            "查看", "判断", "评价", "生成", "提取", "画", "绘制", "表格",
        ]
        knowledge_words = ["是什么", "什么是", "什么意思", "含义", "概念", "定义", "原理"]
        return (
            current_context
            and any(word in lowered for word in action_words)
            and not any(word in lowered for word in knowledge_words)
        )

    def _looks_like_knowledge_formula_request(self, state: ConversationState, text: str) -> bool:
        if self._looks_like_current_signal_request(text):
            return False

        lowered = text.lower()
        explicit_topic = self._extract_knowledge_topic(text)
        if explicit_topic is not None:
            return True

        topic = state.last_knowledge_topic or self._recent_knowledge_topic(state)
        if not topic:
            return False

        markers = [
            "公式", "方程", "推导", "步骤", "原理", "定义", "解释", "说明",
            "详细", "展开", "补充", "参数", "应用", "区别", "联系",
        ]
        return any(marker in lowered for marker in markers)

    def _out_of_scope_message(self) -> str:
        return (
            "我是谛听 · 随机信号智能体，默认只回答随机信号采集、噪声预处理、时域/频域分析、"
            "随机过程知识点和本项目工具使用相关的问题。\n"
            "这个问题超出了我的默认职责范围，所以我不能直接给出答案。"
            "如果你确实需要通用解答，请明确发布指令，例如："
            "“调用外部API回答：你的问题”。"
        )

    def _call_external_general_api(self, sink: list[dict[str, Any]], text: str) -> str:
        question = self._strip_external_general_prefix(text)
        if not self.llm.configured:
            return "外部 API 当前未配置，无法执行通用问答。"
        started = perf_counter()
        call: dict[str, Any] = {
            "tool": "external_general_api",
            "status": "running",
            "arguments": {"question": question[:300]},
        }
        try:
            completion = self.llm.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是外部通用问答模型。本次调用是用户明确授权的非随机信号问题解答。"
                            "用中文直接回答；如果问题涉及医疗、法律、金融等高风险内容，只给一般信息并建议咨询专业人士。"
                        ),
                    },
                    {"role": "user", "content": question},
                ],
                tools=None,
                tool_choice=None,
                temperature=0.2,
                max_tokens=1400,
                timeout=20.0,
            )
            call["status"] = "success"
            call["result_summary"] = "external answer generated"
            answer = completion.content or "外部 API 没有返回有效文本。"
            if completion.finish_reason == "length" and answer:
                answer = self._continue_external_general_answer(question, answer)
            return answer
        except Exception as exc:
            call["status"] = "error"
            call["error"] = str(exc)
            return f"外部 API 调用失败：{exc}"
        finally:
            call["duration_ms"] = round((perf_counter() - started) * 1000, 2)
            sink.append(call)

    def _continue_external_general_answer(self, question: str, partial_answer: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是外部通用问答模型。请只续写未完成的部分，保持原有语言、格式和语气，不要重复前文。"
                ),
            },
            {"role": "user", "content": question},
            {"role": "assistant", "content": partial_answer},
            {"role": "user", "content": "上面的回答被截断了。请继续，只补充尚未完成的内容。"},
        ]
        pieces = [partial_answer]
        for _ in range(2):
            completion = self.llm.complete(
                messages,
                tools=None,
                tool_choice=None,
                temperature=0.2,
                max_tokens=1200,
                timeout=20.0,
            )
            chunk = completion.content.strip()
            if not chunk:
                break
            pieces.append(chunk)
            if completion.finish_reason != "length":
                break
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是外部通用问答模型。请只续写未完成的部分，保持原有语言、格式和语气，不要重复前文。"
                    ),
                },
                {"role": "user", "content": question},
                {"role": "assistant", "content": "\n".join(pieces)},
                {"role": "user", "content": "继续，只补充尚未完成的内容。"},
            ]
        return "\n".join(piece for piece in pieces if piece).strip()

    def _strip_external_general_prefix(self, text: str) -> str:
        for marker in ["调用外部API回答：", "调用外部 API回答：", "调用外部 API 回答：", "用外部API回答：", "用外部 API 回答："]:
            if marker in text:
                return text.split(marker, 1)[1].strip() or text
        for marker in ["调用外部api回答:", "调用外部 api回答:", "external api:"]:
            lowered = text.lower()
            idx = lowered.find(marker)
            if idx >= 0:
                return text[idx + len(marker):].strip() or text
        return text

    def _extract_knowledge_topic(self, text: str) -> str | None:
        lowered = text.lower().replace(" ", "")
        topics: list[tuple[str, str]] = [
            ("卡尔曼滤波", "卡尔曼滤波"),
            ("kalmanfilter", "卡尔曼滤波"),
            ("kalman", "卡尔曼滤波"),
            ("卡尔曼", "卡尔曼滤波"),
            ("ar模型", "AR模型"),
            ("armodel", "AR模型"),
            ("autoregressive", "AR模型"),
            ("自回归", "AR模型"),
            ("自相关", "自相关分析"),
            ("autocorrelation", "自相关分析"),
            ("功率谱估计", "功率谱估计"),
            ("功率谱", "功率谱估计"),
            ("psd", "功率谱估计"),
            ("welch", "功率谱估计"),
            ("预测残差", "预测残差分析"),
            ("残差", "预测残差分析"),
            ("谱熵", "谱熵"),
            ("频域分析", "频域分析"),
            ("频谱", "频域分析"),
            ("fft", "频域分析"),
            ("时域分析", "时域分析"),
            ("均方根", "时域分析"),
            ("rms", "时域分析"),
            ("随机过程", "随机过程"),
            ("随机信号", "随机信号"),
            ("白噪声", "白噪声"),
            ("高斯噪声", "高斯噪声"),
            ("高斯白噪声", "高斯白噪声"),
            ("低通滤波", "低通滤波"),
            ("中值滤波", "中值滤波"),
            ("滑动平均", "滑动平均"),
            ("指数平滑", "指数平滑"),
        ]
        for marker, topic in topics:
            if marker in lowered:
                return topic
        return None

    def _looks_like_knowledge_followup(
        self,
        state: ConversationState,
        text: str,
        detected: str,
    ) -> bool:
        if state.last_intent != "knowledge":
            return False
        if self._looks_like_current_signal_request(text):
            return False
        if detected in {"acquire", "preprocess", "analyze", "reset", "status", "help", "stop_realtime"}:
            return False

        lowered = text.lower()
        followup_markers = [
            "它", "其", "这个", "这种", "该方法", "该模型", "该参数", "它们", "二者", "两者",
            "刚刚", "刚才", "上面", "前面", "上一轮", "继续", "再详细", "详细", "详细解释", "解释一下", "说明一下", "展开", "补充",
            "公式", "推导", "原理", "步骤", "参数", "应用", "优缺点", "区别", "联系",
            "怎么用", "有什么用", "举例", "例子", "再讲", "再说",
        ]
        if any(marker in lowered for marker in followup_markers):
            return True

        topic = self._extract_knowledge_topic(text)
        return topic is not None and self._looks_like_knowledge_question(text)

    def _resolve_knowledge_text(self, state: ConversationState, text: str) -> str:
        topic = state.last_knowledge_topic or self._recent_knowledge_topic(state)
        explicit_topic = self._extract_knowledge_topic(text)
        if not topic:
            return text
        lowered = text.lower()
        contextual_markers = [
            "它", "其", "这个", "这种", "该方法", "该模型", "它们", "二者", "两者",
            "刚刚", "刚才", "上面", "前面", "上一轮", "继续", "再详细", "详细", "详细解释", "解释一下", "说明一下", "公式",
            "推导", "区别", "联系", "优缺点", "应用", "参数",
        ]
        is_contextual = any(marker in lowered for marker in contextual_markers)
        if is_contextual or explicit_topic is None:
            return f"上一轮知识主题是“{topic}”。用户追问：{text}"
        return text

    def _mark_knowledge_context(self, state: ConversationState, text: str) -> None:
        explicit_topic = self._extract_knowledge_topic(text)
        previous_topic = state.last_knowledge_topic or self._recent_knowledge_topic(state)
        lowered = text.lower()
        is_comparison = any(word in lowered for word in ["区别", "比较", "联系", "不同", "相同", "和", "与"])
        if explicit_topic:
            if previous_topic and explicit_topic != previous_topic and is_comparison:
                state.last_knowledge_topic = f"{previous_topic} 与 {explicit_topic}"
            else:
                state.last_knowledge_topic = explicit_topic
        elif previous_topic:
            state.last_knowledge_topic = previous_topic
        state.last_knowledge_question = text
        state.last_intent = "knowledge"

    def _recent_knowledge_topic(self, state: ConversationState) -> str | None:
        for item in reversed(state.messages[-12:]):
            if item.get("role") != "user":
                continue
            content = str(item.get("content") or "")
            topic = self._extract_knowledge_topic(content)
            if topic:
                return topic
        return None

    def _answer_signal_knowledge(self, state: ConversationState, text: str) -> str:
        resolved_text = self._resolve_knowledge_text(state, text)
        if self.llm.configured:
            try:
                answer = self._generate_knowledge_answer(resolved_text)
                if answer:
                    self._mark_knowledge_context(state, resolved_text)
                    return answer
            except Exception:
                pass
        local_formula_answer = self._local_formula_answer(resolved_text)
        if local_formula_answer is not None:
            self._mark_knowledge_context(state, resolved_text)
            return local_formula_answer
        answer = self._local_signal_knowledge(resolved_text)
        self._mark_knowledge_context(state, resolved_text)
        return answer

    def _generate_knowledge_answer(self, resolved_text: str) -> str:
        prompt = [
            {
                "role": "system",
                "content": (
                    "你是随机信号课程知识助手，只回答随机信号、随机过程、噪声、滤波、"
                    "时域/频域分析、功率谱、自相关、AR模型、卡尔曼滤波和本项目工具相关知识。"
                    "请用中文回答。用户如果要求详细解释、公式、步骤、列表或完整推导，"
                    "请给出足够完整的回答，不要压缩成一句话。"
                    "公式必须分行输出，使用有序列表编号，每个公式单独占一行，"
                    "并且保留编号，不要把多个公式拼成一行。"
                    "所有公式必须用 $...$ 或 $$...$$ 包裹，不要输出裸 LaTeX。"
                    "下标写成 x_k 或 x_{k|k-1}，转置写成 H_k^T，逆写成 (... )^{-1}，"
                    "不要使用 Unicode 上标、倒置字母或花体替代符号。"
                ),
            },
            {"role": "user", "content": resolved_text},
        ]
        completion = self.llm.complete(
            prompt,
            tools=None,
            tool_choice=None,
            temperature=0.15,
            max_tokens=3200 if self._wants_formula_detail(resolved_text) else 1800,
            timeout=18.0,
        )
        answer = completion.content.strip()
        if completion.finish_reason == "length" and answer:
            answer = self._continue_knowledge_answer(prompt, answer)
        return answer

    def _continue_knowledge_answer(self, prompt: list[dict[str, str]], partial_answer: str) -> str:
        messages = [
            *prompt,
            {"role": "assistant", "content": partial_answer},
            {
                "role": "user",
                "content": "上面的回答被截断了。请只续写未完成的部分，保持原来的编号、格式和语气，不要重复已经说过的内容。",
            },
        ]
        pieces = [partial_answer]
        for _ in range(2):
            completion = self.llm.complete(
                messages,
                tools=None,
                tool_choice=None,
                temperature=0.15,
                max_tokens=1800,
                timeout=18.0,
            )
            chunk = completion.content.strip()
            if not chunk:
                break
            pieces.append(chunk)
            if completion.finish_reason != "length":
                break
            messages = [
                *prompt,
                {"role": "assistant", "content": "\n".join(pieces)},
                {"role": "user", "content": "继续，只补充尚未完成的内容，不要重复前文。"},
            ]
        return "\n".join(piece for piece in pieces if piece).strip()

    def _local_signal_knowledge(self, text: str) -> str:
        lowered = text.lower()
        if "卡尔曼" in lowered and ("ar" in lowered or "自回归" in lowered) and any(word in lowered for word in ["区别", "比较", "联系"]):
            return (
                "卡尔曼滤波和 AR 模型都属于随机信号处理方法，但定位不同。"
                "AR 模型用历史样本建立随机过程的线性预测模型，重点是建模和预测；"
                "卡尔曼滤波用状态空间模型递推估计真实状态，重点是融合观测与模型来降噪、跟踪和预测。"
            )
        if ("ar" in lowered or "自回归" in lowered) and "公式" in lowered:
            return (
                "AR(p) 模型把当前样本表示为历史样本的线性组合："
                "X_t = phi_1 X_t-1 + phi_2 X_t-2 + ... + phi_p X_t-p + epsilon_t。"
                "其中 phi_i 是模型系数，epsilon_t 通常表示白噪声残差。"
            )
        if "自相关" in lowered and "公式" in lowered:
            return (
                "自相关函数可写为 R_xx(tau) = E[x(t)x(t+tau)]；"
                "离散情形常写作 R_xx[k] = E[x[n]x[n+k]]。"
                "它描述随机过程在不同时间间隔下的相似程度。"
            )
        if ("功率谱" in lowered or "psd" in lowered) and "公式" in lowered:
            return (
                "功率谱密度与自相关函数互为傅里叶变换："
                "S_xx(f) = F{R_xx(tau)}。"
                "工程实现中常用 FFT 或 Welch 分段平均来估计功率谱。"
            )
        if "自相关" in lowered:
            return (
                "自相关函数描述随机信号与其延迟版本之间的相似程度，常写作 Rxx(tau)。"
                "它能反映信号的时间相关性、周期性和记忆长度；延迟越大相关性衰减越快，说明随机过程记忆越短。"
            )
        if "功率谱" in lowered or "psd" in lowered:
            return "功率谱描述信号功率随频率的分布，可由自相关函数傅里叶变换得到，也可用 FFT/Welch 方法估计。"
        if "谱熵" in lowered:
            return "谱熵衡量频谱能量分布的分散程度。能量越集中，谱熵越低；宽带噪声或多频成分越明显，谱熵越高。"
        if "卡尔曼" in lowered:
            return "卡尔曼滤波是一种基于状态空间模型的递推估计方法，可用于随机信号去噪、状态估计和预测。"
        if "ar" in lowered or "自回归" in lowered:
            return "AR 模型用当前样本与若干历史样本的线性组合描述随机过程，适合刻画短时相关性并做一步预测。"
        return "这是随机信号相关问题。你可以继续问自相关、功率谱、谱熵、AR 模型、卡尔曼滤波或时域/频域特征的具体含义。"

    def _local_formula_answer(self, text: str) -> str | None:
        lowered = text.lower()
        if "卡尔曼" in lowered and any(word in lowered for word in ["公式", "方程", "递推", "步骤", "5个", "五个", "核心"]):
            return (
                "卡尔曼滤波五个核心公式（离散时间）：\n"
                "1. 状态预测：$x_{k|k-1}=F_k x_{k-1|k-1}+B_k u_k$\n"
                "2. 协方差预测：$P_{k|k-1}=F_k P_{k-1|k-1} F_k^T+Q_k$\n"
                "3. 卡尔曼增益：$K_k=P_{k|k-1} H_k^T (H_k P_{k|k-1} H_k^T+R_k)^{-1}$\n"
                "4. 状态更新：$x_{k|k}=x_{k|k-1}+K_k (y_k-H_k x_{k|k-1})$\n"
                "5. 协方差更新：$P_{k|k}=(I-K_k H_k) P_{k|k-1}$"
            )
        if ("ar" in lowered or "自回归" in lowered) and any(word in lowered for word in ["公式", "方程", "递推"]):
            return (
                "AR(p) 模型常用公式：\n"
                "1. 递推表达：$x_t=\\sum_{i=1}^{p}\\phi_i x_{t-i}+\\varepsilon_t$\n"
                "2. 白噪声残差：$E[\\varepsilon_t]=0,\\,Var(\\varepsilon_t)=\\sigma^2$"
            )
        if "自相关" in lowered and any(word in lowered for word in ["公式", "方程"]):
            return (
                "自相关函数公式：\n"
                "1. 连续形式：$R_{xx}(\\tau)=E[x(t)x(t+\\tau)]$\n"
                "2. 离散形式：$R_{xx}[k]=E[x[n]x[n+k]]$"
            )
        if ("功率谱" in lowered or "psd" in lowered) and any(word in lowered for word in ["公式", "方程"]):
            return (
                "功率谱密度与自相关函数的关系：\n"
                "1. 正变换：$S_{xx}(f)=\\mathcal{F}\\{R_{xx}(\\tau)\\}$\n"
                "2. 反变换：$R_{xx}(\\tau)=\\mathcal{F}^{-1}\\{S_{xx}(f)\\}$"
            )
        return None

    def _wants_formula_detail(self, text: str) -> bool:
        lowered = text.lower()
        return any(word in lowered for word in ["公式", "方程", "递推", "步骤", "推导", "五个", "5个", "核心"])

    def _chat_locally(
        self,
        state: ConversationState,
        text: str,
        turn_tool_calls: list[dict[str, Any]],
        agent_mode: bool = False,
    ) -> tuple[str, str]:
        """Use the deterministic local router when the external model is unavailable."""

        intent = (
            "preprocess"
            if state.pending_preprocess_request and self._looks_like_preprocess_selection(text)
            else self._detect_intent(text)
        )
        if intent == "help":
            answer = self._help()
        elif intent == "reset":
            self._reset_state(state)
            answer = "已重置当前会话。你可以说“采集一段随机信号”，或上传 CSV/TXT 后说“分析上传的信号”。"
        elif intent == "stop_realtime":
            answer = self._call_tool(turn_tool_calls, "stop_realtime_acquisition", self._stop_realtime_state, state, None)
            if agent_mode and state.bundle is not None:
                answer = answer + "\n" + self._run_agent_autopipeline(state, text, turn_tool_calls)
        elif intent == "acquire":
            answer = self._call_tool(
                turn_tool_calls,
                "acquire_signal",
                self._acquire,
                state,
                text,
                agent_mode,
            )
            if agent_mode:
                plan = state.acquisition_plan or {}
                if plan.get("channel") == "realtime_stream" and not plan.get("realtime_stopped"):
                    answer = answer + "\n" + self._agent_realtime_wait_message()
                    return answer, intent
                answer = answer + "\n" + self._run_agent_autopipeline(state, text, turn_tool_calls)
                return answer, intent
            requested_methods = self._extract_preprocess_methods(text)
            wants_comparison = self._wants_preprocess_comparison(text)
            wants_preprocess = (
                self._mentions_preprocess(text)
                or bool(requested_methods)
                or wants_comparison
                or self._wants_append_preprocess(text)
                or self._wants_all_preprocess_methods(text)
            )
            if wants_preprocess:
                if self._should_ask_preprocess_method(state, text, requested_methods, wants_comparison):
                    state.pending_preprocess_request = text
                    answer = answer + "\n" + self._preprocess_method_prompt()
                else:
                    compare_methods = wants_comparison or len(requested_methods) >= 2
                    method_arg: str | list[str] = requested_methods[0] if requested_methods else "robust_mean"
                    if self._wants_all_preprocess_methods(text):
                        method_arg = list(PREPROCESS_METHODS.keys())
                    elif compare_methods:
                        method_arg = requested_methods or list(PREPROCESS_METHODS.keys())
                    answer = answer + "\n" + self._call_tool(
                        turn_tool_calls,
                        "compare_preprocess_methods" if compare_methods else "preprocess_signal",
                        self._preprocess,
                        state,
                        text,
                        method_arg,
                    )
                    if self._wants_analysis(text):
                        answer = answer + "\n" + self._call_tool(
                            turn_tool_calls,
                            "analyze_signal",
                            self._analyze,
                            state,
                            text,
                        )
            elif self._wants_analysis(text):
                answer = answer + "\n" + self._call_tool(
                    turn_tool_calls,
                    "analyze_signal",
                    self._analyze,
                    state,
                    text,
                )
        elif intent == "preprocess":
            requested_methods = self._extract_preprocess_methods(text)
            wants_comparison = self._wants_preprocess_comparison(text)
            should_ask = self._should_ask_preprocess_method(state, text, requested_methods, wants_comparison)
            if should_ask:
                stop_note = self._ensure_realtime_stopped(state)
                state.pending_preprocess_request = text
                answer = f"{stop_note}\n{self._preprocess_method_prompt()}".strip() if stop_note else self._preprocess_method_prompt()
            else:
                effective_text = (
                    f"{state.pending_preprocess_request} {text}"
                    if state.pending_preprocess_request
                    else text
                )
                compare_all_methods = self._wants_all_preprocess_methods(effective_text)
                compare_methods = wants_comparison or len(requested_methods) >= 2
                if self._wants_append_preprocess(effective_text) and state.preprocess_results:
                    compare_methods = True
                method_arg: str | list[str] = requested_methods[0] if requested_methods else "robust_mean"
                if compare_all_methods:
                    method_arg = list(PREPROCESS_METHODS.keys())
                elif compare_methods:
                    method_arg = requested_methods or list(state.preprocess_results.keys()) or list(PREPROCESS_METHODS.keys())
                answer = self._call_tool(
                    turn_tool_calls,
                    "compare_preprocess_methods" if compare_methods else "preprocess_signal",
                    self._preprocess,
                    state,
                    effective_text,
                    method_arg,
                )
                if self._wants_analysis(effective_text):
                    answer = answer + "\n" + self._call_tool(
                        turn_tool_calls,
                        "analyze_signal",
                        self._analyze,
                        state,
                        effective_text,
                    )
        elif intent == "analyze":
            answer = self._call_tool(turn_tool_calls, "analyze_signal", self._analyze, state, text)
        elif intent == "explain":
            answer = self._call_tool(turn_tool_calls, "explain_result", self._explain, state)
        elif intent == "status":
            answer = self._status(state)
        else:
            answer = self._fallback(state)

        return answer, intent

    def _chat_with_model_tools(
        self,
        state: ConversationState,
        text: str,
        turn_tool_calls: list[dict[str, Any]],
    ) -> tuple[str, str]:
        """Let the external model issue OpenAI-style tool calls, then execute them locally."""

        intent = (
            "preprocess"
            if state.pending_preprocess_request and self._looks_like_preprocess_selection(text)
            else self._detect_intent(text)
        )
        final_messages, direct_answer, intent = self._prepare_model_tool_response(
            state,
            text,
            turn_tool_calls,
            intent,
        )
        if final_messages is not None:
            return self._local_final_answer(state, text), intent
        return direct_answer or self._fallback(state), intent

    def _prepare_model_tool_response(
        self,
        state: ConversationState,
        text: str,
        turn_tool_calls: list[dict[str, Any]],
        intent: str,
    ) -> tuple[list[dict[str, Any]] | None, str, str]:
        """Run model-issued tool calls and return final answer messages."""

        messages = self._model_messages(state, text)
        planned_tools = self._planned_model_tools(state, text, intent)
        tools = self._llm_tools()
        tool_results: list[str] = []
        first_completion_content = ""

        for step in range(6):
            forced_tool = planned_tools.pop(0) if planned_tools else None
            tool_choice: str | dict[str, Any] | None = (
                self._force_tool_choice(forced_tool) if forced_tool else "auto"
            )
            try:
                completion = self.llm.complete(
                    messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=0.1,
                    max_tokens=500,
                    timeout=12.0,
                )
            except LLMClientError:
                if forced_tool:
                    result = self._execute_planned_tool(state, text, forced_tool, turn_tool_calls)
                    tool_results.append(result)
                    if not planned_tools:
                        final_messages = self._final_answer_messages(state, text, turn_tool_calls)
                        return final_messages, "", intent
                    continue
                raise
            assistant_message = completion.message
            first_completion_content = first_completion_content or completion.content
            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                if forced_tool:
                    raise LLMClientError(f"model did not call required tool {forced_tool}")
                if completion.content:
                    return None, completion.content, intent
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_message.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )
            for tool_call in tool_calls:
                result = self._execute_model_tool_call(state, text, tool_call, turn_tool_calls)
                tool_results.append(result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(tool_call.get("id") or ""),
                        "name": self._tool_call_name(tool_call),
                        "content": self._compact_tool_result(result),
                    }
                )

            if not planned_tools:
                break

        if tool_results:
            final_messages = self._final_answer_messages(state, text, turn_tool_calls)
            return final_messages, "", intent

        return None, first_completion_content or self._fallback(state), intent

    def _model_messages(self, state: ConversationState, text: str) -> list[dict[str, Any]]:
        history = [
            {"role": item["role"], "content": item["content"]}
            for item in state.messages[-4:-1]
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]
        return [
            {"role": "system", "content": self._model_system_prompt(state)},
            *history,
            {"role": "user", "content": text},
        ]

    def _final_answer_messages(
        self,
        state: ConversationState,
        text: str,
        turn_tool_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tool_lines = []
        for call in turn_tool_calls[-6:]:
            status = call.get("status", "")
            summary = call.get("result_summary") or call.get("error") or ""
            tool_lines.append(f"- {call.get('tool', 'tool')} / {status}: {summary}")
        return [
            {
                "role": "system",
                "content": (
                    "你是随机信号分析智能体。只基于给定状态和工具摘要回复，禁止补充不存在的数值。"
                    "输出中文，控制在 180 字内；可以使用 Markdown 加粗和列表。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户指令：{text}\n"
                    f"当前状态：{self._state_brief(state)}\n"
                    f"工具摘要：\n" + "\n".join(tool_lines) + "\n"
                    f"关键结果：\n{self._analysis_brief(state)}\n"
                    "请给出最终回复和下一步建议。"
                ),
            },
        ]

    def _execute_planned_tool(
        self,
        state: ConversationState,
        text: str,
        tool_name: str,
        sink: list[dict[str, Any]],
    ) -> str:
        if tool_name == "list_preprocess_methods":
            state.pending_preprocess_request = text
            return self._call_tool(sink, "list_preprocess_methods", self._list_preprocess_methods_tool, state)
        if tool_name == "acquire_signal":
            return self._call_tool(sink, "acquire_signal", self._acquire, state, text)
        if tool_name == "preprocess_signal":
            requested_methods = self._extract_preprocess_methods(text)
            method = requested_methods[0] if requested_methods else "robust_mean"
            return self._call_tool(sink, "preprocess_signal", self._preprocess, state, text, method)
        if tool_name == "compare_preprocess_methods":
            methods = self._extract_preprocess_methods(text) or list(PREPROCESS_METHODS.keys())
            return self._call_tool(sink, "compare_preprocess_methods", self._preprocess, state, text, methods)
        if tool_name == "analyze_signal":
            return self._call_tool(sink, "analyze_signal", self._analyze, state, text)
        if tool_name == "explain_result":
            return self._call_tool(sink, "explain_result", self._explain, state)
        if tool_name == "get_status":
            return self._call_tool(sink, "get_status", self._status, state)
        if tool_name == "reset_session":
            return self._call_tool(sink, "reset_session", self._reset_state, state)
        if tool_name == "stop_realtime_acquisition":
            return self._call_tool(sink, "stop_realtime_acquisition", self._stop_realtime_state, state, None)
        raise LLMClientError(f"unknown planned tool: {tool_name}")

    def _polish_local_answer(self, state: ConversationState, text: str, local_answer: str) -> str:
        return local_answer or self._local_final_answer(state, text)

    def _local_final_answer(self, state: ConversationState, text: str = "") -> str:
        if state.pending_preprocess_request:
            status = self._status(state) if state.bundle is not None else ""
            return f"{status}\n{self._preprocess_method_prompt()}".strip()
        if state.summary is None:
            return self._status(state)
        if self._wants_domain_table(text):
            return f"分析完成。\n{self._series_feature_report(state, text)}"
        lines = [
            "已完成工具调用和分析。",
            f"- 当前状态：{self._state_brief(state)}",
            f"- 关键结果：{self._analysis_brief(state)}",
        ]
        if state.preprocess_comparison is not None:
            labels = [
                str(item.get("label") or item.get("method"))
                for item in state.preprocess_comparison.get("methods", [])
            ]
            lines.append(
                f"- 预处理曲线：已展示 {'、'.join(labels)}；"
                f"当前推荐 {state.preprocess_comparison.get('recommended_label', '未选择')}。"
            )
        if state.decision is not None:
            actions = "；".join(state.decision.get("recommended_actions", [])[:3])
            lines.append(f"- 建议：{actions or state.decision.get('status', '继续观察')}")
        return "\n".join(lines)

    def _analysis_brief(self, state: ConversationState) -> str:
        if state.summary is None:
            return "尚未完成时频域分析。"
        freq = state.summary["frequency_features"]
        time_features = state.summary["time_features"]
        quality = state.summary["quality"]
        advanced = state.summary.get("advanced_analysis") or {}
        ar = advanced.get("ar_model") or {}
        residual = advanced.get("prediction_residual") or {}
        snr = quality.get("processed_snr_db")
        snr_text = "未计算" if snr is None else f"{snr:.2f} dB"
        return (
            f"主频 {freq['dominant_frequency_hz']:.2f} Hz；"
            f"谱熵 {freq['spectral_entropy']:.3f}；"
            f"谱带宽 {freq['spectral_bandwidth_hz']:.2f} Hz；"
            f"RMS {time_features['rms']:.3f}；"
            f"一阶自相关 {time_features['lag1_autocorrelation']:.3f}；"
            f"SNR {snr_text}；"
            f"异常点率 {quality['anomaly_rate'] * 100:.2f}%；"
            f"AR({int(ar.get('order', 0))}) 残差方差 {float(ar.get('noise_variance', 0.0)):.4f}；"
            f"残差白化分数 {float(residual.get('whiteness_score', 0.0)):.3f}。"
        )

    def _wants_domain_table(self, text: str) -> bool:
        lowered = text.lower()
        return any(word in lowered for word in ["时域", "频域", "时频", "频谱", "fft", "随机过程", "ar模型", "ar 模型", "自回归", "自相关", "功率谱估计", "预测残差"])

    def _wants_advanced_analysis(self, text: str) -> bool:
        lowered = text.lower()
        return any(word in lowered for word in ["高级", "随机过程", "ar模型", "ar 模型", "自回归", "自相关", "功率谱估计", "预测残差", "残差分析"])

    def _analysis_scope(self, text: str) -> str:
        lowered = text.lower()
        wants_time = "时域" in lowered or "时频" in lowered
        wants_frequency = any(word in lowered for word in ["频域", "频谱", "fft"])
        if "时频" in lowered:
            wants_frequency = True
        if wants_time and not wants_frequency:
            return "time"
        if wants_frequency and not wants_time:
            return "frequency"
        return "both"

    def _series_feature_report(self, state: ConversationState, text: str = "") -> str:
        if state.bundle is None:
            return "当前没有信号，请先采集或上传信号文件。"
        scope = self._analysis_scope(text)
        series_items = self._current_series_analyses(state)
        lines: list[str] = []
        if scope in {"frequency", "both"}:
            lines.extend(self._frequency_feature_table(series_items))
        if scope == "both":
            lines.append("")
        if scope in {"time", "both"}:
            lines.extend(self._time_feature_table(series_items))
        if self._wants_advanced_analysis(text):
            if lines:
                lines.append("")
            lines.extend(self._advanced_feature_table(series_items))
        return "\n".join(lines).strip()

    def _current_series_analyses(self, state: ConversationState) -> list[dict[str, Any]]:
        if state.bundle is None:
            return []
        items = [
            self._analysis_for_series(
                state,
                "observed",
                "原始观测",
                state.bundle.observed,
                None,
            )
        ]
        if state.preprocess_comparison is not None:
            seen: set[str] = set()
            for item in state.preprocess_comparison.get("methods", []):
                method = item.get("method")
                result = state.preprocess_results.get(method)
                if result is None or method in seen:
                    continue
                seen.add(method)
                items.append(
                    self._analysis_for_series(
                        state,
                        f"processed_{method}",
                        str(item.get("label") or result.method_label),
                        result.signal,
                        result,
                    )
                )
        elif state.processed is not None:
            items.append(
                self._analysis_for_series(
                    state,
                    "processed",
                    state.processed.method_label,
                    state.processed.signal,
                    state.processed,
                )
            )
        return items

    def _frequency_feature_table(self, series_items: list[dict[str, Any]]) -> list[str]:
        lines = [
            "频域特征参数：",
            "| 图线 | 平均频率(Hz) | 重心频率(Hz) | 均方根频率(Hz) | 频率方差(Hz²) | 频率标准差(Hz) |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for item in series_items:
            features = item["summary"]["frequency_features"]
            lines.append(
                f"| {item['label']} | "
                f"{self._fmt(features.get('mean_frequency_hz'))} | "
                f"{self._fmt(features.get('spectral_centroid_hz'))} | "
                f"{self._fmt(features.get('rms_frequency_hz'))} | "
                f"{self._fmt(features.get('frequency_variance_hz2'))} | "
                f"{self._fmt(features.get('frequency_std_hz'))} |"
            )
        return lines

    def _time_feature_table(self, series_items: list[dict[str, Any]]) -> list[str]:
        lines = [
            "时域特征参数：",
            "| 图线 | 均值 | 标准差 | 均方根值 | 峰值 | 峰峰值 | 峰值因子 | 偏度 | 峭度 | 脉冲因子 | 波形因子 | 裕度因子 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for item in series_items:
            features = item["summary"]["time_features"]
            lines.append(
                f"| {item['label']} | "
                f"{self._fmt(features.get('mean'))} | "
                f"{self._fmt(features.get('std'))} | "
                f"{self._fmt(features.get('rms'))} | "
                f"{self._fmt(features.get('peak'))} | "
                f"{self._fmt(features.get('peak_to_peak'))} | "
                f"{self._fmt(features.get('crest_factor'))} | "
                f"{self._fmt(features.get('skewness'))} | "
                f"{self._fmt(features.get('kurtosis'))} | "
                f"{self._fmt(features.get('impulse_factor'))} | "
                f"{self._fmt(features.get('shape_factor'))} | "
                f"{self._fmt(features.get('clearance_factor'))} |"
            )
        return lines

    def _fmt(self, value: Any, digits: int = 3) -> str:
        if value is None:
            return "未计算"
        try:
            return f"{float(value):.{digits}f}"
        except (TypeError, ValueError):
            return str(value)

    def _advanced_feature_table(self, series_items: list[dict[str, Any]]) -> list[str]:
        lines = [
            "随机过程高级分析：",
            "| 图线 | AR阶数 | AR残差方差 | AR稳定半径 | 相关长度(lag) | Welch主频(Hz) | Welch谱熵 | 残差RMS | 残差白化分数 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for item in series_items:
            advanced = item["summary"].get("advanced_analysis") or {}
            ar = advanced.get("ar_model") or {}
            autocorr = advanced.get("autocorrelation") or {}
            psd = advanced.get("power_spectrum") or {}
            residual = advanced.get("prediction_residual") or {}
            lines.append(
                f"| {item['label']} | "
                f"{int(ar.get('order', 0))} | "
                f"{self._fmt(ar.get('noise_variance'), 4)} | "
                f"{self._fmt(ar.get('stability_radius'))} | "
                f"{int(autocorr.get('correlation_length_lag', 0))} | "
                f"{self._fmt(psd.get('dominant_frequency_hz'))} | "
                f"{self._fmt(psd.get('spectral_entropy'))} | "
                f"{self._fmt(residual.get('rms'))} | "
                f"{self._fmt(residual.get('whiteness_score'))} |"
            )
        return lines

    def _model_system_prompt(self, state: ConversationState) -> str:
        methods = ", ".join(f"{item['id']}={item['label']}" for item in list_preprocess_methods())
        return (
            "你是一个云端随机信号分析智能体，必须通过 OpenAI tool call 调用后端工具完成会改变或读取"
            "信号状态的任务，包括采集、预处理、方法比较、时域频域分析、结果解释、状态查询和重置。"
            "默认只回答随机信号、随机过程、噪声处理和本项目工具相关问题；与这些主题无关的问题不要直接回答，"
            "应说明需要用户明确要求调用外部 API 才能做通用问答。"
            "不要凭空编造采样点、SNR、主频、谱熵或异常点数量。用户要求多个步骤时，应按顺序调用多个工具。"
            "采集随机信号时不要主动设置 seed；只有用户明确给出 seed、随机种子或种子数值时才传 seed。"
            "如果用户要求自主采集、自动巡检、多渠道或多通道采集，应调用 acquire_signal，并把 channel 设为 "
            "autonomous_sweep、realtime_stream 或 sensor_gateway 中最合适的一项；如果用户指定了信号/噪声模型，"
            "必须保留用户指定模型，不要自动预处理。"
            "如果用户只说预处理但没有指定方法，先调用 list_preprocess_methods，再询问用户要使用哪种方法；"
            "如果用户要求比较两种或多种预处理方法，调用 compare_preprocess_methods。"
            "最终回复使用中文，简洁说明已调用的工具、关键结果和下一步建议。\n"
            f"可用预处理方法：{methods}。\n"
            f"当前状态：{self._state_brief(state)}"
        )

    def _llm_tools(self) -> list[dict[str, Any]]:
        method_enum = list(PREPROCESS_METHODS.keys())
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_preprocess_methods",
                    "description": "List available noise preprocessing methods before asking the user to choose.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "acquire_signal",
                    "description": "Acquire a simulated random signal window.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sample_rate": {"type": "number", "description": "Sampling rate in Hz. Default 200."},
                            "duration": {"type": "number", "description": "Signal duration in seconds. Default 8, or 60 for realtime_stream when omitted by the user."},
                            "base_frequency": {"type": "number", "description": "Target dominant frequency in Hz. Default 8."},
                            "noise_std": {"type": "number", "description": "Gaussian noise standard deviation. Default 0.55."},
                            "channel": {
                                "type": "string",
                                "enum": ["simulated_lab", "realtime_stream", "autonomous_sweep", "sensor_gateway"],
                                "description": "Acquisition channel. Use autonomous_sweep for autonomous/multi-channel inspection, realtime_stream for real-time acquisition, sensor_gateway for hardware/API gateway requests.",
                            },
                            "goal": {
                                "type": "string",
                                "description": "Acquisition goal such as preprocess_benchmark, spectral_identification, nonstationary_tracking, impulse_robustness.",
                            },
                            "signal_model": {
                                "type": "string",
                                "enum": ["random_process", "sine_gaussian"],
                                "description": "Legacy alias. Prefer waveform and noise_model for explicit signal-noise combinations.",
                            },
                            "waveform": {
                                "type": "string",
                                "enum": ["random_process", "sine", "square", "triangle", "sawtooth", "multi_sine", "chirp"],
                                "description": "Base signal type requested by the user.",
                            },
                            "noise_model": {
                                "type": "string",
                                "enum": ["mixed", "gaussian", "uniform", "impulse", "ar", "gaussian_impulse"],
                                "description": "Noise/interference type requested by the user.",
                            },
                            "seed": {
                                "type": "integer",
                                "description": "Only set this when the user explicitly provides a seed/random seed.",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "preprocess_signal",
                    "description": "Apply one noise preprocessing method to the current signal.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "method": {"type": "string", "enum": method_enum},
                            "smoothing_window": {"type": "integer", "description": "Odd smoothing window size. Default 7."},
                            "anomaly_threshold_sigma": {"type": "number", "description": "Robust anomaly threshold in sigma. Default 3."},
                            "lowpass_cutoff_hz": {"type": "number", "description": "FFT low-pass cutoff frequency in Hz."},
                            "ema_alpha": {"type": "number", "description": "EMA smoothing coefficient between 0 and 1."},
                            "kalman_process_noise": {"type": "number", "description": "Kalman process noise covariance Q."},
                            "kalman_measurement_noise": {"type": "number", "description": "Kalman measurement noise covariance R."},
                            "kalman_initial_error": {"type": "number", "description": "Kalman initial estimate error covariance P."},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "compare_preprocess_methods",
                    "description": "Compare multiple preprocessing methods and choose the best one by quality score.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "methods": {
                                "type": "array",
                                "items": {"type": "string", "enum": method_enum},
                                "description": "Methods to compare. Omit or pass empty to compare all methods.",
                            },
                            "smoothing_window": {"type": "integer", "description": "Odd smoothing window size. Default 7."},
                            "anomaly_threshold_sigma": {"type": "number", "description": "Robust anomaly threshold in sigma. Default 3."},
                            "lowpass_cutoff_hz": {"type": "number", "description": "FFT low-pass cutoff frequency in Hz."},
                            "ema_alpha": {"type": "number", "description": "EMA smoothing coefficient between 0 and 1."},
                            "kalman_process_noise": {"type": "number", "description": "Kalman process noise covariance Q."},
                            "kalman_measurement_noise": {"type": "number", "description": "Kalman measurement noise covariance R."},
                            "kalman_initial_error": {"type": "number", "description": "Kalman initial estimate error covariance P."},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "analyze_signal",
                    "description": "Extract time-domain, frequency-domain and advanced random-process features from the current signal.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "explain_result",
                    "description": "Explain the latest analysis result and give signal-processing suggestions.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_status",
                    "description": "Return current session status.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "reset_session",
                    "description": "Reset current signal, analysis result, and tool history.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "stop_realtime_acquisition",
                    "description": "Stop the current realtime stream and keep the samples acquired so far.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    def _planned_model_tools(self, state: ConversationState, text: str, intent: str) -> list[str]:
        if intent == "reset":
            return ["reset_session"]
        if intent == "stop_realtime":
            return ["stop_realtime_acquisition"]
        if intent == "status":
            return ["get_status"]
        if intent == "analyze":
            return ["analyze_signal"]
        if intent == "explain":
            return ["explain_result"]
        if intent == "preprocess":
            tools = ["acquire_signal"] if state.bundle is None or self._mentions_acquire(text) else []
            requested_methods = self._extract_preprocess_methods(text)
            wants_comparison = self._wants_preprocess_comparison(text)
            if self._should_ask_preprocess_method(state, text, requested_methods, wants_comparison):
                tools.append("list_preprocess_methods")
                return tools
            tools.append(
                "compare_preprocess_methods"
                if wants_comparison or len(requested_methods) >= 2 or self._wants_append_preprocess(text)
                else "preprocess_signal"
            )
            if self._wants_analysis(text):
                tools.append("analyze_signal")
            return tools
        if intent == "acquire":
            tools = ["acquire_signal"]
            requested_methods = self._extract_preprocess_methods(text)
            wants_comparison = self._wants_preprocess_comparison(text)
            wants_preprocess = (
                self._mentions_preprocess(text)
                or bool(requested_methods)
                or wants_comparison
                or self._wants_append_preprocess(text)
                or self._wants_all_preprocess_methods(text)
            )
            if wants_preprocess:
                if self._should_ask_preprocess_method(
                    state,
                    text,
                    requested_methods,
                    wants_comparison,
                ):
                    tools.append("list_preprocess_methods")
                else:
                    tools.append(
                        "compare_preprocess_methods"
                        if wants_comparison or len(requested_methods) >= 2 or self._wants_append_preprocess(text)
                        else "preprocess_signal"
                    )
                    if self._wants_analysis(text):
                        tools.append("analyze_signal")
            elif self._wants_analysis(text):
                tools.append("analyze_signal")
            return tools
        return []

    def _force_tool_choice(self, tool_name: str) -> dict[str, Any]:
        return {"type": "function", "function": {"name": tool_name}}

    def _execute_model_tool_call(
        self,
        state: ConversationState,
        original_text: str,
        tool_call: dict[str, Any],
        sink: list[dict[str, Any]],
    ) -> str:
        name = self._tool_call_name(tool_call)
        args = self._tool_call_arguments(tool_call)
        before = len(sink)

        if name == "list_preprocess_methods":
            result = self._call_tool(sink, "list_preprocess_methods", self._list_preprocess_methods_tool, state)
        elif name == "acquire_signal":
            result = self._call_tool(sink, "acquire_signal", self._acquire_from_model_args, state, original_text, args)
        elif name == "preprocess_signal":
            result = self._call_tool(
                sink,
                "preprocess_signal",
                self._preprocess_from_model_args,
                state,
                original_text,
                args,
                False,
            )
        elif name == "compare_preprocess_methods":
            result = self._call_tool(
                sink,
                "compare_preprocess_methods",
                self._preprocess_from_model_args,
                state,
                original_text,
                args,
                True,
            )
        elif name == "analyze_signal":
            result = self._call_tool(sink, "analyze_signal", self._analyze, state, original_text)
        elif name == "explain_result":
            result = self._call_tool(sink, "explain_result", self._explain, state)
        elif name == "get_status":
            result = self._call_tool(sink, "get_status", self._status, state)
        elif name == "reset_session":
            result = self._call_tool(sink, "reset_session", self._reset_state, state)
        elif name == "stop_realtime_acquisition":
            result = self._call_tool(sink, "stop_realtime_acquisition", self._stop_realtime_state, state, None)
        else:
            raise LLMClientError(f"unknown tool call: {name}")

        if len(sink) > before:
            sink[-1]["model_tool_call_id"] = str(tool_call.get("id") or "")
            sink[-1]["model_arguments_raw"] = args
        return result

    def _tool_call_name(self, tool_call: dict[str, Any]) -> str:
        function = tool_call.get("function") or {}
        return str(function.get("name") or tool_call.get("name") or "")

    def _tool_call_arguments(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        function = tool_call.get("function") or {}
        raw_args = function.get("arguments") or tool_call.get("arguments") or {}
        if isinstance(raw_args, dict):
            return raw_args
        if not isinstance(raw_args, str) or not raw_args.strip():
            return {}
        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _compact_tool_result(self, result: str) -> str:
        return result if len(result) <= 2500 else result[:2500] + "\n...（工具结果已截断）"

    def _state_brief(self, state: ConversationState) -> str:
        if state.bundle is None:
            return "尚未采集或上传信号"
        parts = [
            f"已有信号，样本数 {state.bundle.observed.size}",
            f"采样率 {state.bundle.config.sample_rate:.2f} Hz",
            f"来源 {state.bundle.source}",
        ]
        if state.acquisition_plan is not None:
            parts.append(f"采集通道 {state.acquisition_plan.get('channel_label', state.acquisition_plan.get('channel'))}")
        if state.processed is not None:
            parts.append(f"已预处理：{state.processed.method_label}")
        if state.summary is not None:
            freq = state.summary["frequency_features"]["dominant_frequency_hz"]
            parts.append(f"已分析，主频 {freq:.2f} Hz")
        return "，".join(parts)

    def _list_preprocess_methods_tool(self, state: ConversationState) -> str:
        state.pending_preprocess_request = state.pending_preprocess_request or "预处理"
        lines = ["可用噪声预处理方法："]
        for item in list_preprocess_methods():
            lines.append(f"- {item['id']} / {item['label']}：{item['description']}")
        lines.append("请用户选择一种方法，或要求比较多种/全部方法。")
        return "\n".join(lines)

    def _acquire_from_model_args(
        self,
        state: ConversationState,
        original_text: str,
        args: dict[str, Any],
    ) -> str:
        sample_rate = self._number_arg(args, "sample_rate", self._extract_sample_rate(original_text, default=200.0))
        frequency = self._number_arg(args, "base_frequency", self._extract_frequency(original_text, default=8.0))
        noise = self._number_arg(args, "noise_std", self._number_after(original_text, ["噪声", "noise"], default=0.55))
        waveform = self._waveform_from_text(original_text, str(args.get("waveform") or args.get("signal_model") or ""))
        noise_model = self._noise_model_from_text(original_text, str(args.get("noise_model") or args.get("signal_model") or ""))
        channel = str(args.get("channel") or "").strip()
        resolved_channel = channel or self._acquisition_channel_from_text(
            original_text,
            self._wants_autonomous_acquisition(original_text),
        )
        if resolved_channel == "realtime_stream" and not self._has_explicit_duration(original_text):
            duration = 60.0
        else:
            duration = self._number_arg(args, "duration", self._extract_duration(original_text, default=8.0))
        seed = (
            self._int_arg(args, "seed", self._extract_seed(original_text))
            if self._text_mentions_seed(original_text)
            else None
        )
        seed_text = f" seed {seed}" if seed is not None else ""
        channel_text = f" 采集通道 {channel}" if channel else ""
        tool_text = (
            f"采样率 {sample_rate} Hz 时长 {duration} 秒 主频 {frequency} Hz "
            f"噪声 {noise} 基准信号 {waveform} 噪声模型 {noise_model}{channel_text}{seed_text}"
        )
        return self._acquire(state, tool_text)

    def _text_mentions_seed(self, text: str) -> bool:
        lowered = text.lower()
        return "seed" in lowered or "随机种子" in text or "种子" in text

    def _preprocess_from_model_args(
        self,
        state: ConversationState,
        original_text: str,
        args: dict[str, Any],
        force_compare: bool,
    ) -> str:
        local_methods = self._extract_preprocess_methods(original_text)
        methods: str | list[str] | None
        if force_compare:
            arg_methods = args.get("methods")
            if isinstance(arg_methods, list):
                methods = [str(item) for item in arg_methods if str(item).strip()]
            else:
                methods = []
            if local_methods:
                methods = local_methods
            if self._wants_append_preprocess(original_text) and state.preprocess_results:
                methods = list(dict.fromkeys(list(state.preprocess_results.keys()) + list(methods)))
            if self._wants_all_preprocess_methods(original_text):
                methods = list(PREPROCESS_METHODS.keys())
            if not methods:
                methods = list(PREPROCESS_METHODS.keys())
        else:
            method = str(args.get("method") or "").strip()
            methods = local_methods[0] if local_methods else (method or "robust_mean")

        tool_text = self._explicit_preprocess_text(original_text, args)
        return self._preprocess(state, tool_text, methods)

    def _explicit_preprocess_text(self, original_text: str, args: dict[str, Any]) -> str:
        parts: list[str] = []
        value = self._explicit_preprocess_number(original_text, args, "smoothing_window", ["窗口", "window", "平滑"])
        if value is not None:
            parts.append(f"窗口 {int(value)}")
        value = self._explicit_preprocess_number(original_text, args, "anomaly_threshold_sigma", ["阈值", "sigma"])
        if value is not None:
            parts.append(f"阈值 {value}")
        value = self._explicit_preprocess_number(original_text, args, "lowpass_cutoff_hz", ["截止频率", "截止", "cutoff", "低通"])
        if value is not None:
            parts.append(f"截止 {value}")
        value = self._explicit_preprocess_number(original_text, args, "ema_alpha", ["alpha", "系数"])
        if value is not None:
            parts.append(f"alpha {value}")
        value = self._explicit_preprocess_number(original_text, args, "kalman_process_noise", ["过程噪声", "process", " q", "Q"])
        if value is not None:
            parts.append(f"过程噪声 {value}")
        value = self._explicit_preprocess_number(original_text, args, "kalman_measurement_noise", ["测量噪声", "measurement", " r", "R"])
        if value is not None:
            parts.append(f"测量噪声 {value}")
        value = self._explicit_preprocess_number(original_text, args, "kalman_initial_error", ["初始误差", "initial", " p", "P"])
        if value is not None:
            parts.append(f"初始误差 {value}")
        return " ".join(parts)

    def _explicit_preprocess_number(
        self,
        text: str,
        args: dict[str, Any],
        key: str,
        words: list[str],
    ) -> float | None:
        parsed = self._number_after(text, words, default=None)
        if parsed is not None:
            return float(parsed)
        if self._contains_any(text, words) and self._contains_number(text):
            value = args.get(key)
            if value is not None and value != "":
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
        return None

    def _contains_any(self, text: str, words: list[str]) -> bool:
        lowered = text.lower()
        return any(word.lower() in lowered for word in words)

    def _contains_number(self, text: str) -> bool:
        import re

        return re.search(r"\d+(?:\.\d+)?", text) is not None

    def _number_arg(self, args: dict[str, Any], key: str, default: float) -> float:
        value = args.get(key)
        if value is None or value == "":
            return float(default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _int_arg(self, args: dict[str, Any], key: str, default: int | None) -> int | None:
        value = args.get(key)
        if value is None or value == "":
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def use_uploaded_file(
        self,
        session_id: str,
        file_path: str,
        sample_rate: float = 200.0,
        tool_library: dict[str, Any] | None = None,
        agent_mode: bool = False,
    ) -> dict[str, Any]:
        """Load an uploaded signal file into a session."""
        state = self.get_session(session_id)
        self._update_tool_library(state, tool_library)
        turn_tool_calls: list[dict[str, Any]] = []
        self._call_tool(
            turn_tool_calls,
            "load_signal_file",
            self._load_uploaded_signal,
            state,
            file_path,
            sample_rate,
        )
        assert state.bundle is not None
        answer = (
            f"已接收文件信号，共 {state.bundle.observed.size} 个样本，"
            f"采样率约 {state.bundle.config.sample_rate:.2f} Hz。"
            "你可以继续说“预处理并分析”。"
        )
        if agent_mode:
            answer = answer + "\n" + self._run_agent_autopipeline(
                state,
                "Agent 模式：上传文件后自动比较全部预处理方法并分析",
                turn_tool_calls,
            )
        state.messages.append({"role": "assistant", "content": answer})
        state.tool_calls.extend(turn_tool_calls)
        return {
            "reply": answer,
            "state": self.serialize_state(state),
            "intent": "upload",
            "tool_calls": turn_tool_calls,
        }

    def use_microphone_samples(
        self,
        session_id: str,
        samples: list[float],
        sample_rate: float,
    ) -> dict[str, Any]:
        """Load browser microphone samples into a session as sensor-gateway data."""
        state = self.get_session(session_id)
        turn_tool_calls: list[dict[str, Any]] = []
        self._call_tool(
            turn_tool_calls,
            "load_microphone_signal",
            self._load_microphone_signal,
            state,
            samples,
            sample_rate,
        )
        state.tool_calls.extend(turn_tool_calls)
        assert state.bundle is not None
        answer = (
            f"已通过电脑麦克风采集真实音频信号，共 {state.bundle.observed.size} 个样本，"
            f"采样率约 {state.bundle.config.sample_rate:.1f} Hz，"
            f"时长 {state.bundle.config.duration:.2f} s。"
            "已自动识别噪声画像并执行强噪声画像抵消，"
            "中间图谱已切换到降噪后结果，页面下方可在线播放或下载音频。"
        )
        state.messages.append({"role": "assistant", "content": answer})
        return {
            "reply": answer,
            "state": self.serialize_state(state),
            "intent": "microphone",
            "tool_calls": turn_tool_calls,
        }

    def stop_realtime_acquisition(
        self,
        session_id: str,
        sample_count: int | None = None,
        tool_library: dict[str, Any] | None = None,
        agent_mode: bool = False,
    ) -> dict[str, Any]:
        """Stop a simulated realtime stream and keep the samples received so far."""
        state = self.get_session(session_id)
        self._update_tool_library(state, tool_library)
        turn_tool_calls: list[dict[str, Any]] = []
        answer = self._stop_realtime_state(state, sample_count)
        if agent_mode and state.bundle is not None:
            answer = answer + "\n" + self._run_agent_autopipeline(
                state,
                "Agent 模式：实时采集停止后自动比较全部预处理方法并分析",
                turn_tool_calls,
            )
        state.messages.append({"role": "assistant", "content": answer})
        state.tool_calls.extend(turn_tool_calls)
        return {
            "reply": answer,
            "state": self.serialize_state(state),
            "intent": "stop_realtime",
            "tool_calls": turn_tool_calls,
        }

    def _reset_state(self, state: ConversationState) -> str:
        session_id = state.session_id
        state.diagnostic_lab = {}
        state.bundle = None
        state.processed = None
        state.summary = None
        state.decision = None
        state.preprocess_results = {}
        state.preprocess_comparison = None
        state.pending_preprocess_request = None
        state.messages = []
        state.tool_calls = []
        state.last_uploaded_path = None
        state.acquisition_plan = None
        state.acquisition_history = []
        state.audio_result = None
        state.last_knowledge_topic = None
        state.last_knowledge_question = None
        state.last_intent = None
        self.sessions[session_id] = state
        return "已重置当前会话。"

    def _stop_realtime_state(self, state: ConversationState, sample_count: int | None = None) -> str:
        if state.bundle is None:
            return "当前没有正在采集的实时信号。"
        plan = state.acquisition_plan or {}
        if plan.get("channel") != "realtime_stream":
            return "当前信号不是实时流式采集通道，无需停止。"
        if plan.get("realtime_stopped"):
            return (
                "实时流式采集已经停止，当前图谱就是停止时保留的最终采集窗口。"
                "可以直接对这段最终信号继续预处理、比较或分析。"
            )

        total = int(state.bundle.observed.size)
        if total <= 0:
            return "实时采集数据为空，无法停止。"
        requested = total if sample_count is None else int(sample_count)
        keep = max(8, min(total, requested))

        old_config = state.bundle.config
        duration = keep / max(float(old_config.sample_rate), 1e-12)
        new_config = SignalConfig(
            sample_rate=old_config.sample_rate,
            duration=duration,
            base_frequency=old_config.base_frequency,
            amplitude=old_config.amplitude,
            noise_std=old_config.noise_std,
            ar_coefficient=old_config.ar_coefficient,
            impulse_probability=old_config.impulse_probability,
            seed=old_config.seed,
            signal_model=old_config.signal_model,
            waveform=old_config.waveform,
            noise_model=old_config.noise_model,
        )
        source = state.bundle.source
        if "/stopped" not in source:
            source = f"{source}/stopped"
        state.diagnostic_lab = {}
        state.bundle = SignalBundle(
            time=state.bundle.time[:keep],
            clean=state.bundle.clean[:keep],
            observed=state.bundle.observed[:keep],
            noise=state.bundle.noise[:keep],
            impulse_mask=state.bundle.impulse_mask[:keep],
            config=new_config,
            source=source,
            has_clean_reference=state.bundle.has_clean_reference,
        )

        state.processed = None
        state.summary = None
        state.decision = None
        state.preprocess_results = {}
        state.preprocess_comparison = None
        state.pending_preprocess_request = None
        state.audio_result = None

        plan = dict(plan)
        plan["realtime_stopped"] = True
        plan["stopped_sample_count"] = keep
        plan["stopped_duration"] = duration
        plan["policy"] = f"{plan.get('policy', '实时流式采集')}；已在 {duration:.2f} s 停止并保留全过程样本"
        plan_config = dict(plan.get("config") or {})
        plan_config.update(new_config.to_dict())
        plan["config"] = plan_config
        state.acquisition_plan = plan
        if state.acquisition_history:
            state.acquisition_history[-1] = plan

        return (
            f"已停止实时流式采集，保留停止前的整个采集过程："
            f"{keep} 个样本，约 {duration:.2f} s。现在可以对这段数据进行预处理、时域分析或频域分析。"
        )

    def _load_uploaded_signal(
        self,
        state: ConversationState,
        file_path: str,
        sample_rate: float,
    ) -> str:
        state.diagnostic_lab = {}
        state.bundle = load_signal_file(file_path, sample_rate=sample_rate)
        state.processed = None
        state.summary = None
        state.decision = None
        state.preprocess_results = {}
        state.preprocess_comparison = None
        state.pending_preprocess_request = None
        state.last_uploaded_path = file_path
        state.audio_result = None
        plan = {
            "channel": "uploaded_file",
            "channel_label": "用户文件通道",
            "channel_description": "从用户上传的 CSV/TXT 数据中读取信号样本。",
            "autonomous": False,
            "available": True,
            "policy": "使用用户上传文件作为采集来源",
            "goal": "uploaded_signal_analysis",
            "candidate_channels": ["uploaded_file"],
            "config": state.bundle.config.to_dict(),
        }
        state.acquisition_plan = plan
        state.acquisition_history.append(plan)
        state.acquisition_history = state.acquisition_history[-8:]
        return f"载入文件信号 {state.bundle.observed.size} 点"

    def _agent_realtime_wait_message(self) -> str:
        return (
            "Agent 模式已开启：实时流式采集当前先按时间片动态接收信号。"
            "点击“停止采集”或输入预处理/分析指令后，我会锁定停止时的完整采集结果，"
            "再自动进入全方法预处理比较和时频域分析。"
        )

    def _run_agent_autopipeline(
        self,
        state: ConversationState,
        text: str,
        turn_tool_calls: list[dict[str, Any]],
    ) -> str:
        if state.bundle is None:
            return "当前没有信号，请先采集或上传信号文件。"

        self._call_tool(
            turn_tool_calls,
            "compare_preprocess_methods",
            self._preprocess,
            state,
            text or "Agent 模式：比较全部预处理方法",
            list(PREPROCESS_METHODS.keys()),
            "autonomous",
        )
        self._call_tool(
            turn_tool_calls,
            "analyze_signal",
            self._analyze,
            state,
            "时域 频域 表格",
        )

        assert state.processed is not None
        best_label = state.processed.method_label
        best_method = state.processed.method
        best_params = self._format_agent_parameters(state.processed.parameters)
        best_report = self._best_series_feature_report(state)
        rows = state.preprocess_comparison.get("methods", []) if state.preprocess_comparison else []
        score_line = ""
        if rows:
            top = rows[0]
            score_line = f"综合评分：{self._fmt(top.get('score'))}。"

        return (
            f"Agent 模式自动处理完成。\n"
            f"- 最优预处理方式：{best_label}（{best_method}）。{score_line}\n"
            f"- 最优参数：{best_params}\n"
            "- 中间区域已展示原始信号和全部预处理方法曲线，可点击图例切换对应频域图和知识分析。\n\n"
            f"{best_report}"
        ).strip()

    def _format_agent_parameters(self, parameters: dict[str, Any] | None) -> str:
        if not parameters:
            return "无额外参数"
        labels = {
            "window": "窗口",
            "anomaly_threshold_sigma": "异常阈值σ",
            "robust_sigma": "鲁棒尺度",
            "alpha": "EMA系数",
            "cutoff_hz": "截止频率Hz",
            "sample_rate": "采样率Hz",
            "process_noise_q": "过程噪声Q",
            "measurement_noise_r": "测量噪声R",
            "initial_error_p": "初始误差P",
        }
        parts: list[str] = []
        for key, value in parameters.items():
            label = labels.get(key, key)
            parts.append(f"{label}={self._fmt(value)}")
        return "，".join(parts)

    def _best_series_feature_report(self, state: ConversationState) -> str:
        assert state.processed is not None
        item = self._analysis_for_series(
            state,
            f"processed_{state.processed.method}",
            state.processed.method_label,
            state.processed.signal,
            state.processed,
        )
        lines: list[str] = ["最优处理后的频域特征参数："]
        lines.extend(self._frequency_feature_table([item])[1:])
        lines.append("")
        lines.append("最优处理后的时域特征参数：")
        lines.extend(self._time_feature_table([item])[1:])
        lines.append("")
        lines.append("最优处理后的随机过程高级分析：")
        lines.extend(self._advanced_feature_table([item])[1:])
        return "\n".join(lines)

    def _load_microphone_signal(
        self,
        state: ConversationState,
        samples: list[float],
        sample_rate: float,
    ) -> str:
        observed = np.asarray(samples, dtype=float)
        observed = observed[np.isfinite(observed)]
        if observed.size < 16:
            raise ValueError("麦克风样本过少，至少需要 16 个有效采样点。")
        sample_rate = float(min(max(sample_rate, 1.0), 192000.0))
        observed = observed - float(np.mean(observed))
        peak = float(np.max(np.abs(observed))) if observed.size else 0.0
        if peak > 1.0:
            observed = observed / peak
        time = np.arange(observed.size, dtype=float) / sample_rate
        duration = observed.size / sample_rate
        config = SignalConfig(
            sample_rate=sample_rate,
            duration=duration,
            base_frequency=8.0,
            amplitude=1.0,
            noise_std=float(np.std(observed)),
            ar_coefficient=0.0,
            impulse_probability=0.0,
            seed=0,
            signal_model="microphone_audio",
            waveform="microphone_audio",
            noise_model="ambient",
        )
        state.diagnostic_lab = {}
        state.bundle = SignalBundle(
            time=time,
            clean=observed.copy(),
            observed=observed,
            noise=np.zeros_like(observed),
            impulse_mask=np.zeros(observed.size, dtype=bool),
            config=config,
            source="sensor_gateway/computer_microphone",
            has_clean_reference=False,
        )
        state.processed = None
        state.summary = None
        state.decision = None
        state.preprocess_results = {}
        state.preprocess_comparison = None
        state.pending_preprocess_request = None
        state.last_uploaded_path = None
        denoised, denoise_info = self._noise_cancellation_denoise_enhanced(observed, sample_rate)
        audio_result = self._export_audio_result(state.session_id, observed, denoised, sample_rate, denoise_info)
        state.processed = PreprocessResult(
            signal=denoised,
            anomaly_mask=np.zeros(observed.size, dtype=bool),
            removed_mean=0.0,
            smoothing_window=1,
            method="noise_cancellation",
            method_label="强噪声画像抵消",
            parameters=denoise_info,
        )
        state.preprocess_results = {"noise_cancellation": state.processed}
        state.summary = self._summarize_processed(state, state.processed)
        state.audio_result = audio_result
        plan = {
            "channel": "sensor_gateway",
            "channel_label": "外部传感器网关",
            "channel_description": "浏览器 Web Audio API 读取本机电脑麦克风并上传采样数据。",
            "autonomous": True,
            "available": True,
            "policy": "使用当前浏览器授权的电脑麦克风作为外部传感器输入，并自动执行噪声画像抵消降噪",
            "goal": "computer_microphone_signal_analysis",
            "candidate_channels": ["sensor_gateway"],
            "config": config.to_dict(),
            "gateway": "computer_microphone",
            "auto_denoise": "noise_profile_cancellation",
        }
        state.acquisition_plan = plan
        state.acquisition_history.append(plan)
        state.acquisition_history = state.acquisition_history[-8:]
        return f"载入电脑麦克风信号 {observed.size} 点"

    def _noise_cancellation_denoise_enhanced(
        self,
        signal: np.ndarray,
        sample_rate: float,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Speech-preserving cancellation for single-mic ambient noise.

        This is intentionally not a conventional fixed filter. It estimates a
        time-frequency noise image from low-speech frames, subtracts that image
        more aggressively outside speech-dominant regions, and applies residual
        spectral gating between spoken segments.
        """
        x = np.asarray(signal, dtype=float)
        if x.size < 32:
            return x.copy(), {"method": "speech_preserving_noise_cancellation", "noise_frames": 0}
        x = x - float(np.mean(x))

        frame_size = int(min(max(512, round(sample_rate * 0.032)), 4096))
        frame_size = min(frame_size, max(32, x.size))
        hop = max(1, frame_size // 4)
        window = np.hanning(frame_size)
        if not np.any(window):
            window = np.ones(frame_size, dtype=float)

        if x.size <= frame_size:
            pad_right = frame_size - x.size
        else:
            pad_right = (hop - ((x.size - frame_size) % hop)) % hop
        padded = np.pad(x, (0, pad_right), mode="constant")
        starts = list(range(0, max(1, padded.size - frame_size + 1), hop))
        if starts[-1] + frame_size < padded.size:
            starts.append(padded.size - frame_size)

        raw_frames = np.stack([padded[start:start + frame_size] for start in starts])
        frames = raw_frames * window
        spectrum = np.fft.rfft(frames, axis=1)
        magnitude = np.abs(spectrum)
        phase = np.angle(spectrum)
        freqs = np.fft.rfftfreq(frame_size, d=1.0 / max(float(sample_rate), 1.0))
        energy = np.mean(raw_frames**2, axis=1)

        voice_mask = (freqs >= 120.0) & (freqs <= min(4200.0, float(sample_rate) * 0.48))
        if not np.any(voice_mask):
            voice_mask = np.ones_like(freqs, dtype=bool)
        low_mask = freqs < 120.0
        high_mask = freqs > min(5200.0, float(sample_rate) * 0.42)

        total_mag = np.sum(magnitude, axis=1) + 1e-12
        voice_ratio = np.sum(magnitude[:, voice_mask], axis=1) / total_mag
        e_low, e_high = np.percentile(energy, [12, 88])
        v_low, v_high = np.percentile(voice_ratio, [20, 90])
        energy_score = np.clip((energy - e_low) / max(e_high - e_low, 1e-12), 0.0, 1.0)
        voice_score = np.clip((voice_ratio - v_low) / max(v_high - v_low, 1e-12), 0.0, 1.0)
        speech_presence = np.clip(0.62 * energy_score + 0.38 * voice_score, 0.0, 1.0)
        if speech_presence.size >= 3:
            speech_presence = np.convolve(speech_presence, np.array([0.18, 0.64, 0.18]), mode="same")
            speech_presence = np.clip(speech_presence, 0.0, 1.0)

        quiet_count = max(1, min(len(energy), int(np.ceil(len(energy) * 0.30))))
        quiet_score = 0.65 * energy_score + 0.35 * speech_presence
        quiet_indices = np.argsort(quiet_score)[:quiet_count]
        quiet_profile = np.median(magnitude[quiet_indices], axis=0)
        low_percentile_profile = np.percentile(magnitude, 8, axis=0)
        minimum_statistics_profile = np.sqrt(np.maximum(np.percentile(magnitude**2, 5, axis=0), 1e-16))
        noise_profile = (
            0.58 * quiet_profile
            + 0.30 * low_percentile_profile
            + 0.12 * minimum_statistics_profile
        )
        if noise_profile.size >= 5:
            kernel = np.array([0.08, 0.18, 0.48, 0.18, 0.08], dtype=float)
            noise_profile = np.convolve(noise_profile, kernel, mode="same")

        noise_power = np.maximum(noise_profile**2, 1e-14)
        signal_power = magnitude**2
        posterior_snr = np.maximum((signal_power - noise_power[None, :]) / noise_power[None, :], 0.0)
        band_weight = np.ones_like(freqs, dtype=float)
        band_weight[~voice_mask] = 1.34
        band_weight[low_mask] = 2.25
        band_weight[high_mask] = 1.65
        speech_relief = 1.28 - 0.36 * speech_presence[:, None]
        oversubtraction = (2.20 + 2.55 * np.exp(-posterior_snr / 1.35)) * band_weight[None, :] * speech_relief
        oversubtraction = np.clip(oversubtraction, 1.75, 6.40)

        speech_floor = 0.018 + 0.055 * speech_presence[:, None]
        nonvoice_floor = 0.004 + 0.018 * speech_presence[:, None]
        floor_ratio = np.where(voice_mask[None, :], speech_floor, nonvoice_floor)
        cancelled_power = np.maximum(
            signal_power - oversubtraction * noise_power[None, :],
            (floor_ratio * magnitude) ** 2,
        )
        gain = np.sqrt(cancelled_power) / np.maximum(magnitude, 1e-12)
        wiener_gain = posterior_snr / (posterior_snr + 1.65)
        gain = np.minimum(gain, 0.62 * gain + 0.38 * wiener_gain)

        snr_db = 10.0 * np.log10((signal_power + 1e-14) / (noise_power[None, :] + 1e-14))
        soft_gate = 1.0 / (1.0 + np.exp(-(snr_db - 1.5) / 2.8))
        gain *= 0.24 + 0.76 * soft_gate

        voice_floor = (0.035 + 0.105 * speech_presence[:, None])
        residual_floor = np.where(voice_mask[None, :], voice_floor, 0.008 + 0.018 * speech_presence[:, None])
        gain = np.maximum(gain, residual_floor)

        gate_floor = 0.045
        frame_gate = gate_floor + (1.0 - gate_floor) * np.power(speech_presence, 0.82)
        gain = gain * frame_gate[:, None]
        gain = np.clip(gain, 0.006, 1.0)

        if gain.shape[0] > 1:
            smoothed = gain.copy()
            for idx in range(1, smoothed.shape[0]):
                current_mean = float(np.mean(smoothed[idx]))
                previous_mean = float(np.mean(smoothed[idx - 1]))
                carry = 0.20 if current_mean >= previous_mean else 0.42
                smoothed[idx] = (1.0 - carry) * smoothed[idx] + carry * smoothed[idx - 1]
            gain = smoothed
        if gain.shape[1] >= 3:
            gain[:, 1:-1] = 0.14 * gain[:, :-2] + 0.72 * gain[:, 1:-1] + 0.14 * gain[:, 2:]

        enhanced = gain * magnitude * np.exp(1j * phase)
        frames_out = np.fft.irfft(enhanced, n=frame_size, axis=1)

        output = np.zeros(padded.size, dtype=float)
        weight = np.zeros(padded.size, dtype=float)
        envelope = np.zeros(padded.size, dtype=float)
        envelope_weight = np.zeros(padded.size, dtype=float)
        synthesis_window = window**2
        frame_envelope = 0.18 + 0.82 * np.power(speech_presence, 0.72)
        for start, frame, env in zip(starts, frames_out, frame_envelope):
            output[start:start + frame_size] += frame * window
            weight[start:start + frame_size] += synthesis_window
            envelope[start:start + frame_size] += env * window
            envelope_weight[start:start + frame_size] += window
        output = output / np.maximum(weight, 1e-8)
        envelope = envelope / np.maximum(envelope_weight, 1e-8)
        output *= np.clip(envelope, 0.12, 1.0)
        output = output[:x.size]
        output = output - float(np.mean(output))

        input_rms = float(np.sqrt(np.mean(x**2))) if x.size else 0.0
        output_rms = float(np.sqrt(np.mean(output**2))) if output.size else 0.0
        if input_rms > 1e-12 and output_rms > 1e-12:
            target_rms = input_rms * 0.62
            if output_rms > target_rms:
                output = output * (target_rms / output_rms)
            elif output_rms < input_rms * 0.22:
                output = output * min((input_rms * 0.34) / output_rms, 1.9)

        peak = float(np.max(np.abs(output))) if output.size else 0.0
        if peak > 0.98:
            output = output / peak * 0.98

        before_noise = float(np.mean(magnitude[quiet_indices]))
        after_noise = float(np.mean((gain * magnitude)[quiet_indices]))
        reduction_db = 20.0 * np.log10((before_noise + 1e-12) / (after_noise + 1e-12))
        return output.astype(float), {
            "method": "speech_preserving_noise_cancellation",
            "description": "Aggressive speech-preserving spectral noise-image cancellation with residual gating.",
            "frame_size": int(frame_size),
            "hop_size": int(hop),
            "noise_frames": int(quiet_count),
            "noise_profile_percentile": 8,
            "oversubtraction_min": 1.75,
            "oversubtraction_max": 6.40,
            "spectral_floor_min": float(np.min(floor_ratio)),
            "spectral_floor_max": float(np.max(floor_ratio)),
            "noise_gate_floor": gate_floor,
            "mean_gain": float(np.mean(gain)),
            "speech_presence_mean": float(np.mean(speech_presence)),
            "attenuated_frame_ratio": float(np.mean(frame_gate < 0.45)),
            "estimated_noise_reduction_db": float(max(0.0, min(reduction_db, 60.0))),
        }

    def _noise_cancellation_denoise(
        self,
        signal: np.ndarray,
        sample_rate: float,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Denoise microphone audio by estimating and cancelling a noise profile."""
        x = np.asarray(signal, dtype=float)
        if x.size < 32:
            return x.copy(), {"method": "noise_profile_cancellation", "noise_frames": 0}
        frame_size = int(min(max(256, round(sample_rate * 0.032)), 2048))
        frame_size = min(frame_size, max(32, x.size))
        hop = max(1, frame_size // 2)
        window = np.hanning(frame_size)
        if not np.any(window):
            window = np.ones(frame_size, dtype=float)

        padded = np.pad(x, (0, max(0, frame_size - x.size % hop)), mode="constant")
        starts = list(range(0, max(1, padded.size - frame_size + 1), hop))
        if starts[-1] + frame_size < padded.size:
            starts.append(padded.size - frame_size)
        frames = np.stack([padded[start:start + frame_size] * window for start in starts])
        spectrum = np.fft.rfft(frames, axis=1)
        magnitude = np.abs(spectrum)
        phase = np.angle(spectrum)
        energy = np.mean(frames**2, axis=1)
        threshold = np.percentile(energy, 25)
        noise_mask = energy <= threshold
        if int(noise_mask.sum()) < max(1, len(energy) // 10):
            quiet_count = max(1, len(energy) // 5)
            quiet_indices = np.argsort(energy)[:quiet_count]
            noise_profile = np.median(magnitude[quiet_indices], axis=0)
            noise_frames = int(quiet_count)
        else:
            noise_profile = np.median(magnitude[noise_mask], axis=0)
            noise_frames = int(noise_mask.sum())

        oversubtraction = 1.25
        floor_ratio = 0.08
        cancelled_mag = np.maximum(magnitude - oversubtraction * noise_profile[None, :], floor_ratio * magnitude)
        gain = cancelled_mag / np.maximum(magnitude, 1e-12)
        gain = np.clip(gain, 0.03, 1.0)
        enhanced = gain * magnitude * np.exp(1j * phase)
        frames_out = np.fft.irfft(enhanced, n=frame_size, axis=1)

        output = np.zeros(padded.size, dtype=float)
        weight = np.zeros(padded.size, dtype=float)
        synthesis_window = window**2
        for start, frame in zip(starts, frames_out):
            output[start:start + frame_size] += frame * window
            weight[start:start + frame_size] += synthesis_window
        output = output / np.maximum(weight, 1e-8)
        output = output[:x.size]
        output = output - float(np.mean(output))
        peak = float(np.max(np.abs(output))) if output.size else 0.0
        if peak > 0.98:
            output = output / peak * 0.98
        input_noise = float(np.mean(noise_profile))
        residual_noise = float(np.mean(np.maximum(cancelled_mag[:, : max(1, cancelled_mag.shape[1] // 4)], 0)))
        reduction_db = 20.0 * np.log10((input_noise + 1e-12) / (residual_noise + 1e-12))
        return output.astype(float), {
            "method": "noise_profile_cancellation",
            "description": "基于低能量片段估计噪声画像，并在短时频谱中执行噪声抵消。",
            "frame_size": int(frame_size),
            "hop_size": int(hop),
            "noise_frames": noise_frames,
            "oversubtraction": oversubtraction,
            "spectral_floor": floor_ratio,
            "estimated_noise_reduction_db": float(max(0.0, min(reduction_db, 60.0))),
        }

    def _export_audio_result(
        self,
        session_id: str,
        original: np.ndarray,
        denoised: np.ndarray,
        sample_rate: float,
        denoise_info: dict[str, Any],
    ) -> dict[str, Any]:
        AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        safe_session = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in session_id)[:64] or "default"
        stem = f"{safe_session}_{secrets.token_hex(4)}"
        original_wav = AUDIO_OUTPUT_DIR / f"{stem}_original.wav"
        denoised_wav = AUDIO_OUTPUT_DIR / f"{stem}_denoised.wav"
        self._write_wav(original_wav, original, sample_rate)
        self._write_wav(denoised_wav, denoised, sample_rate)

        denoised_download = f"/outputs/audio/{denoised_wav.name}"
        download_format = "wav"
        mp3_path = AUDIO_OUTPUT_DIR / f"{stem}_denoised.mp3"
        if self._try_convert_mp3(denoised_wav, mp3_path):
            denoised_download = f"/outputs/audio/{mp3_path.name}"
            download_format = "mp3"

        return {
            "method": "noise_profile_cancellation",
            "method_label": "强噪声画像抵消",
            "original_url": f"/outputs/audio/{original_wav.name}",
            "denoised_url": f"/outputs/audio/{denoised_wav.name}",
            "download_url": denoised_download,
            "download_format": download_format,
            "sample_rate": float(sample_rate),
            "duration": float(len(denoised) / max(sample_rate, 1e-12)),
            "noise_reduction_db": denoise_info.get("estimated_noise_reduction_db"),
            "details": denoise_info,
        }

    def _write_wav(self, path: Path, signal: np.ndarray, sample_rate: float) -> None:
        data = np.asarray(signal, dtype=float)
        data = data - float(np.mean(data)) if data.size else data
        peak = float(np.max(np.abs(data))) if data.size else 0.0
        if peak > 1e-12:
            data = np.clip(data / max(peak, 1.0), -1.0, 1.0)
        pcm = (data * 32767.0).astype("<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(int(round(sample_rate)))
            handle.writeframes(pcm.tobytes())

    def _try_convert_mp3(self, wav_path: Path, mp3_path: Path) -> bool:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return False
        try:
            subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav_path), "-codec:a", "libmp3lame", "-q:a", "3", str(mp3_path)],
                check=True,
                timeout=20,
            )
            return mp3_path.exists() and mp3_path.stat().st_size > 0
        except Exception:
            return False

    def serialize_state(self, state: ConversationState) -> dict[str, Any]:
        """Serialize compact state for browser rendering."""
        from .diagnostics import public_lab
        payload: dict[str, Any] = {
            "session_id": state.session_id,
            "comparison_goal": state.comparison_goal,
            "has_signal": state.bundle is not None,
            "has_processed": state.processed is not None,
            "has_summary": state.summary is not None,
            "last_intent": state.last_intent,
            "last_knowledge_topic": state.last_knowledge_topic,
            "last_knowledge_question": state.last_knowledge_question,
            "selected_series_key": self._default_series_key(state),
            "messages": state.messages[-12:],
            "tool_calls": state.tool_calls[-12:],
        }
        if state.bundle is not None:
            payload["signal"] = {
                "sample_rate": state.bundle.config.sample_rate,
                "sample_count": int(state.bundle.observed.size),
                "source": state.bundle.source,
                "has_clean_reference": state.bundle.has_clean_reference,
                "config": state.bundle.config.to_dict(),
            }
            if state.acquisition_plan is not None:
                payload["signal"]["acquisition_channel"] = state.acquisition_plan.get("channel")
                payload["signal"]["acquisition_channel_label"] = state.acquisition_plan.get("channel_label")
                payload["signal"]["acquisition_policy"] = state.acquisition_plan.get("policy")
                payload["signal"]["acquisition_goal"] = state.acquisition_plan.get("goal")
                payload["signal"]["waveform"] = state.acquisition_plan.get("config", {}).get("waveform")
                payload["signal"]["noise_model"] = state.acquisition_plan.get("config", {}).get("noise_model")
        if state.acquisition_plan is not None:
            payload["acquisition_plan"] = state.acquisition_plan
        payload["available_acquisition_channels"] = list_acquisition_channels()
        if state.processed is not None:
            payload["preprocess"] = {
                "method": state.processed.method,
                "method_label": state.processed.method_label,
                "parameters": state.processed.parameters,
            }
        if state.preprocess_comparison is not None:
            payload["preprocess_comparison"] = state.preprocess_comparison
        if state.audio_result is not None:
            payload["audio_result"] = state.audio_result
        payload["available_preprocess_methods"] = list_preprocess_methods()
        if state.summary is not None:
            payload["summary"] = {
                "time_features": state.summary["time_features"],
                "frequency_features": {
                    key: value
                    for key, value in state.summary["frequency_features"].items()
                    if key != "spectrum"
                },
                "quality": state.summary["quality"],
                "advanced_analysis": state.summary.get("advanced_analysis", {}),
                "insights": self._build_insights(state),
            }
        if state.decision is not None:
            payload["decision"] = state.decision
            payload["risk"] = self._risk_payload(state)
        if state.bundle is not None:
            payload["series"] = self._series_payload(state)
        payload['diagnostic_lab'] = public_lab(state)
        return payload

    def _update_tool_library(
        self,
        state: ConversationState,
        tool_library: dict[str, Any] | None,
    ) -> None:
        if not isinstance(tool_library, dict):
            return
        methods = tool_library.get("preprocess_methods")
        legacy_methods = (
            "random_process_analysis" not in tool_library
            and not isinstance(tool_library.get("preprocess_methods"), dict)
        )
        if not isinstance(methods, dict) and legacy_methods:
            methods = tool_library
        normalized: dict[str, dict[str, Any]] = {}
        if isinstance(methods, dict):
            for raw_method, raw_params in methods.items():
                method = normalize_preprocess_method(str(raw_method))
                if method not in PREPROCESS_METHODS or not isinstance(raw_params, dict):
                    continue
                normalized[method] = self._normalize_library_params(raw_params)
        if normalized:
            state.tool_library.update(normalized)

        random_process = tool_library.get("random_process_analysis")
        if isinstance(random_process, dict):
            normalized_random: dict[str, dict[str, Any]] = {}
            for raw_method, raw_params in random_process.items():
                method = self._normalize_random_process_method(str(raw_method))
                if method is None or not isinstance(raw_params, dict):
                    continue
                normalized_random[method] = self._normalize_random_process_params(method, raw_params)
            if normalized_random:
                state.random_process_library.update(normalized_random)

    def _normalize_library_params(self, raw_params: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for key in [
            "smoothing_window",
            "anomaly_threshold_sigma",
            "lowpass_cutoff_hz",
            "ema_alpha",
            "kalman_process_noise",
            "kalman_measurement_noise",
            "kalman_initial_error",
        ]:
            value = raw_params.get(key)
            if value is None or value == "":
                continue
            try:
                params[key] = float(value)
            except (TypeError, ValueError):
                continue
        if "smoothing_window" in params:
            params["smoothing_window"] = int(min(511, max(1, round(params["smoothing_window"]))))
        if "anomaly_threshold_sigma" in params:
            params["anomaly_threshold_sigma"] = float(min(max(params["anomaly_threshold_sigma"], 0.5), 8.0))
        if "lowpass_cutoff_hz" in params:
            params["lowpass_cutoff_hz"] = float(max(params["lowpass_cutoff_hz"], 0.0))
        if "ema_alpha" in params:
            params["ema_alpha"] = float(min(max(params["ema_alpha"], 0.02), 0.95))
        if "kalman_process_noise" in params:
            params["kalman_process_noise"] = float(min(max(params["kalman_process_noise"], 1e-6), 10.0))
        if "kalman_measurement_noise" in params:
            params["kalman_measurement_noise"] = float(min(max(params["kalman_measurement_noise"], 1e-6), 10.0))
        if "kalman_initial_error" in params:
            params["kalman_initial_error"] = float(min(max(params["kalman_initial_error"], 1e-6), 100.0))
        return params

    def _normalize_random_process_method(self, method: str) -> str | None:
        key = method.strip().lower()
        aliases = {
            "ar_model": "ar_model",
            "ar": "ar_model",
            "ar模型": "ar_model",
            "自回归": "ar_model",
            "autocorrelation": "autocorrelation",
            "acf": "autocorrelation",
            "自相关": "autocorrelation",
            "自相关分析": "autocorrelation",
            "power_spectrum": "power_spectrum",
            "psd": "power_spectrum",
            "功率谱": "power_spectrum",
            "功率谱估计": "power_spectrum",
            "prediction_residual": "prediction_residual",
            "residual": "prediction_residual",
            "预测残差": "prediction_residual",
            "残差分析": "prediction_residual",
        }
        return aliases.get(key)

    def _normalize_random_process_params(self, method: str, raw_params: dict[str, Any]) -> dict[str, Any]:
        numeric: dict[str, float] = {}
        for key, value in raw_params.items():
            if value is None or value == "":
                continue
            try:
                numeric[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        params: dict[str, Any] = {}
        if method == "ar_model":
            if "ar_order" in numeric:
                params["ar_order"] = int(min(max(round(numeric["ar_order"]), 1), 64))
            if "prediction_horizon" in numeric:
                params["prediction_horizon"] = int(min(max(round(numeric["prediction_horizon"]), 1), 256))
        elif method == "autocorrelation":
            if "max_autocorr_lag" in numeric:
                params["max_autocorr_lag"] = int(min(max(round(numeric["max_autocorr_lag"]), 1), 512))
        elif method == "power_spectrum":
            if "psd_segment_length" in numeric:
                params["psd_segment_length"] = int(min(max(round(numeric["psd_segment_length"]), 32), 4096))
            if "psd_overlap" in numeric:
                params["psd_overlap"] = float(min(max(numeric["psd_overlap"], 0.0), 0.9))
        elif method == "prediction_residual":
            if "residual_lag" in numeric:
                params["residual_lag"] = int(min(max(round(numeric["residual_lag"]), 1), 256))
        return params

    def _advanced_config(self, state: ConversationState) -> AdvancedAnalysisConfig:
        params: dict[str, Any] = {}
        for method_params in state.random_process_library.values():
            params.update(method_params)
        return AdvancedAnalysisConfig(
            ar_order=int(params.get("ar_order", 8)),
            prediction_horizon=int(params.get("prediction_horizon", 24)),
            max_autocorr_lag=int(params.get("max_autocorr_lag", 48)),
            psd_segment_length=int(params.get("psd_segment_length", 256)),
            psd_overlap=float(params.get("psd_overlap", 0.5)),
            residual_lag=int(params.get("residual_lag", 24)),
        )

    def _summarize_processed(self, state: ConversationState, processed: PreprocessResult) -> dict[str, Any]:
        assert state.bundle is not None
        return summarize_signal_window(
            state.bundle,
            processed,
            advanced_config=self._advanced_config(state),
        )

    def _summarize_observed(self, state: ConversationState) -> dict[str, Any]:
        assert state.bundle is not None
        signal = state.bundle.observed
        time_features = extract_time_features(signal)
        frequency_features = extract_frequency_features(signal, state.bundle.config.sample_rate)
        if state.bundle.has_clean_reference:
            raw_snr = float(estimate_snr(state.bundle.clean, signal))
        else:
            raw_snr = None
        anomaly_rate = float(state.bundle.impulse_mask.mean()) if state.bundle.impulse_mask.size else 0.0
        summary = {
            "time_features": time_features,
            "frequency_features": frequency_features,
            "quality": {
                "raw_snr_db": raw_snr,
                "processed_snr_db": raw_snr,
                "snr_improvement_db": 0.0 if raw_snr is not None else None,
                "anomaly_rate": anomaly_rate,
                "detected_anomaly_count": int(state.bundle.impulse_mask.sum()),
                "has_clean_reference": state.bundle.has_clean_reference,
            },
            "advanced_analysis": advanced_random_process_analysis(
                signal,
                state.bundle.config.sample_rate,
                self._advanced_config(state),
            ),
        }
        summary["insights"] = self._insights_from_summary(summary)
        return summary

    def _call_tool(
        self,
        sink: list[dict[str, Any]],
        tool_name: str,
        fn: Any,
        *args: Any,
    ) -> str:
        started = perf_counter()
        call: dict[str, Any] = {
            "tool": tool_name,
            "status": "running",
            "arguments": self._tool_arguments(tool_name, args),
        }
        emit_progress(tool_name, "running")
        try:
            result = fn(*args)
            call["status"] = "success"
            call["result_summary"] = self._tool_result_summary(tool_name, args)
            return result
        except Exception as exc:
            call["status"] = "error"
            call["error"] = str(exc)
            raise
        finally:
            call["duration_ms"] = round((perf_counter() - started) * 1000, 2)
            sink.append(call)
            emit_progress(tool_name, call["status"], duration_ms=call["duration_ms"])

    def _tool_arguments(self, tool_name: str, args: tuple[Any, ...]) -> dict[str, Any]:
        if not args:
            return {}
        state = args[0] if isinstance(args[0], ConversationState) else None
        if tool_name == "acquire_signal" and state is not None and len(args) >= 2:
            text = str(args[1])
            model_args = args[2] if len(args) >= 3 and isinstance(args[2], dict) else {}
            seed = self._int_arg(model_args, "seed", None) if self._text_mentions_seed(text) else None
            channel = model_args.get("channel") or self._acquisition_channel_from_text(text, self._wants_autonomous_acquisition(text))
            if channel == "realtime_stream" and not self._has_explicit_duration(text):
                duration = 60.0
            else:
                duration = self._number_arg(model_args, "duration", self._extract_duration(text, default=8.0))
            return {
                "sample_rate": self._number_arg(model_args, "sample_rate", self._extract_sample_rate(text, default=200.0)),
                "duration": duration,
                "base_frequency": self._number_arg(model_args, "base_frequency", self._extract_frequency(text, default=8.0)),
                "noise_std": self._number_arg(model_args, "noise_std", self._number_after(text, ["噪声", "noise"], default=0.55)),
                "seed": seed,
                "channel": channel,
                "waveform": model_args.get("waveform") or self._waveform_from_text(text, str(model_args.get("signal_model") or "")),
                "noise_model": model_args.get("noise_model") or self._noise_model_from_text(text, str(model_args.get("signal_model") or "")),
                "mode": "multi_channel_acquisition" if self._wants_autonomous_acquisition(text) else "simulation",
            }
        if tool_name == "preprocess_signal" and len(args) >= 2:
            text = str(args[1])
            model_args = args[2] if len(args) >= 3 and isinstance(args[2], dict) else {}
            methods = self._extract_preprocess_methods(text)
            fallback_method = args[2] if len(args) >= 3 and not isinstance(args[2], dict) else "robust_mean"
            requested = (
                methods[0]
                if methods
                else (model_args.get("method") or fallback_method)
            )
            method = requested if isinstance(requested, str) else ",".join(requested)
            method_key = normalize_preprocess_method(method)
            library_params = state.tool_library.get(method_key, {}) if state is not None else {}
            return {
                "method": method,
                "smoothing_window": int(self._number_arg(model_args, "smoothing_window", self._number_after(text, ["窗口", "window", "平滑"], default=library_params.get("smoothing_window", 7)))),
                "anomaly_threshold_sigma": self._number_arg(model_args, "anomaly_threshold_sigma", self._number_after(text, ["阈值", "sigma"], default=library_params.get("anomaly_threshold_sigma", 3.0))),
                "lowpass_cutoff_hz": self._number_arg(model_args, "lowpass_cutoff_hz", self._number_after(text, ["截止频率", "截止", "cutoff", "低通"], default=library_params.get("lowpass_cutoff_hz", 0.0))),
                "ema_alpha": self._number_arg(model_args, "ema_alpha", self._number_after(text, ["alpha", "系数"], default=library_params.get("ema_alpha", 0.22))),
                "kalman_process_noise": self._number_arg(model_args, "kalman_process_noise", self._number_after(text, ["过程噪声", "process_noise", "process", "Q"], default=library_params.get("kalman_process_noise", 0.02))),
                "kalman_measurement_noise": self._number_arg(model_args, "kalman_measurement_noise", self._number_after(text, ["测量噪声", "measurement_noise", "measurement", "R"], default=library_params.get("kalman_measurement_noise", 0.25))),
                "kalman_initial_error": self._number_arg(model_args, "kalman_initial_error", self._number_after(text, ["初始误差", "initial_error", "initial", "P"], default=library_params.get("kalman_initial_error", 1.0))),
            }
        if tool_name == "compare_preprocess_methods" and len(args) >= 2:
            text = str(args[1])
            model_args = args[2] if len(args) >= 3 and isinstance(args[2], dict) else {}
            requested = self._extract_preprocess_methods(text) or model_args.get("methods") or (
                args[2] if len(args) >= 3 else []
            )
            methods = list(PREPROCESS_METHODS.keys()) if self._wants_all_preprocess_methods(text) else (
                requested if isinstance(requested, list) else [requested]
            )
            return {
                "methods": methods or list(PREPROCESS_METHODS.keys()),
                "tool_library": state.tool_library if state is not None else {},
                "random_process_library": state.random_process_library if state is not None else {},
            }
        if tool_name == "load_signal_file" and len(args) >= 3:
            return {"sample_rate": float(args[2]), "source": "upload"}
        if tool_name == "load_microphone_signal" and len(args) >= 3:
            sample_count = len(args[1]) if hasattr(args[1], "__len__") else 0
            return {
                "sample_rate": float(args[2]),
                "sample_count": sample_count,
                "source": "computer_microphone",
            }
        if tool_name == "list_preprocess_methods":
            return {"method_count": len(PREPROCESS_METHODS)}
        if tool_name in {"get_status", "reset_session", "stop_realtime_acquisition"}:
            return {}
        return {}

    def _tool_result_summary(self, tool_name: str, args: tuple[Any, ...]) -> str:
        state = args[0] if args and isinstance(args[0], ConversationState) else None
        if state is None:
            return "完成"
        if tool_name in {"acquire_signal", "load_signal_file", "load_microphone_signal"} and state.bundle is not None:
            channel = (state.acquisition_plan or {}).get("channel_label") or state.bundle.source
            return f"{state.bundle.observed.size} samples @ {state.bundle.config.sample_rate:.1f} Hz via {channel}"
        if tool_name == "preprocess_signal" and state.processed is not None:
            return (
                f"{state.processed.method_label}, {int(state.processed.anomaly_mask.sum())} anomalies, "
                f"window={state.processed.smoothing_window}"
            )
        if tool_name == "compare_preprocess_methods" and state.preprocess_comparison is not None:
            count = len(state.preprocess_comparison.get("methods", []))
            best = state.preprocess_comparison.get("recommended_label", "未选择")
            return f"{count} methods compared, recommended={best}"
        if tool_name == "analyze_signal" and state.summary is not None:
            freq = state.summary["frequency_features"]["dominant_frequency_hz"]
            advanced = state.summary.get("advanced_analysis") or {}
            order = (advanced.get("ar_model") or {}).get("order", 0)
            return f"dominant={freq:.2f} Hz, AR({order}) diagnostics ready"
        if tool_name == "explain_result" and state.decision is not None:
            return state.decision["status"]
        if tool_name == "list_preprocess_methods":
            return f"{len(PREPROCESS_METHODS)} methods available"
        if tool_name == "get_status":
            return self._state_brief(state)
        if tool_name == "reset_session":
            return "session reset"
        if tool_name == "stop_realtime_acquisition" and state.bundle is not None:
            return f"stopped at {state.bundle.observed.size} samples"
        return "完成"

    def _detect_intent(self, text: str) -> str:
        lowered = text.lower()
        if any(word in lowered for word in ["帮助", "help", "怎么用", "用法"]):
            return "help"
        if any(word in lowered for word in ["停止采集", "结束采集", "停止实时", "结束实时", "stop realtime", "stop acquisition"]):
            return "stop_realtime"
        if any(word in lowered for word in ["重置", "reset", "清空"]):
            return "reset"
        if any(word in lowered for word in ["解释", "结论", "建议", "为什么", "说明", "意义"]):
            return "explain"
        if any(word in lowered for word in [
            "采集", "重新采集", "再采集", "生成", "模拟", "自主采集", "自动采集", "自动巡检",
            "多通道", "多渠道", "实时采集", "传感器", "sample", "acquire", "collect", "autonomous",
            "multi-channel", "multichannel",
        ]):
            return "acquire"
        if any(word in text for word in ["采集", "重新采集", "再采集", "生成", "模拟", "自主", "多通道", "多渠道", "实时"]):
            return "acquire"
        if (
            any(word in lowered for word in ["预处理", "去噪", "滤波", "平滑", "异常", "中值", "低通", "指数", "鲁棒", "滑动平均", "median", "ema", "hybrid", "kalman", "卡尔曼"])
            or (self._wants_preprocess_comparison(text) and self._wants_all_preprocess_methods(text))
        ):
            return "preprocess"
        if any(word in lowered for word in ["分析", "时域", "频域", "频谱", "fft", "主频", "功率谱", "随机过程", "ar模型", "ar 模型", "自回归", "自相关", "预测残差"]):
            return "analyze"
        if any(word in lowered for word in ["状态", "当前", "结果"]):
            return "status"
        return "unknown"

    def _wants_analysis(self, text: str) -> bool:
        lowered = text.lower()
        analysis_words = ["分析", "时域", "频域", "频谱", "fft", "功率谱", "随机过程", "ar模型", "ar 模型", "自回归", "自相关", "预测残差"]
        if any(word in lowered for word in analysis_words):
            return True
        dominant_frequency_queries = ["主频是多少", "主频为多少", "求主频", "估计主频", "检测主频", "识别主频", "主频分析"]
        return any(word in lowered for word in dominant_frequency_queries)

    def _mentions_preprocess(self, text: str) -> bool:
        lowered = text.lower()
        return any(word in lowered for word in ["预处理", "去噪", "滤波", "平滑", "异常", "降噪"])

    def _mentions_acquire(self, text: str) -> bool:
        lowered = text.lower()
        return any(word in lowered for word in [
            "采集", "生成", "模拟", "随机信号", "自主采集", "自动采集", "自动巡检", "多通道",
            "多渠道", "实时采集", "传感器", "sample", "acquire", "collect", "autonomous",
            "multi-channel", "multichannel",
        ])

    def _looks_like_preprocess_selection(self, text: str) -> bool:
        lowered = text.lower()
        method_words = [
            "robust", "moving_average", "median", "ema", "fft", "lowpass", "hybrid", "kalman",
            "滑动平均", "鲁棒", "中值", "中位数", "指数", "低通", "混合", "卡尔曼",
        ]
        compare_words = ["比较", "对比", "全部", "多种", "多方法", "所有"]
        return any(word in lowered for word in method_words + compare_words)

    def _wants_preprocess_comparison(self, text: str) -> bool:
        lowered = text.lower()
        return any(word in lowered for word in ["比较", "对比", "全部", "所有", "多种", "多方法", "compare", "all"])

    def _wants_all_preprocess_methods(self, text: str) -> bool:
        lowered = text.lower()
        return any(word in lowered for word in ["全部", "所有", "全方法", "全部方法", "所有方法", "all"])

    def _extract_preprocess_methods(self, text: str) -> list[str]:
        lowered = text.lower()
        selected: list[str] = []
        aliases = {
            "robust_mean": ["robust_mean", "robust", "滑动平均", "均值", "鲁棒"],
            "median": ["median", "中值", "中位数"],
            "ema": ["ema", "exponential", "指数", "递推"],
            "fft_lowpass": ["fft", "lowpass", "low-pass", "低通"],
            "hybrid": ["hybrid", "mix", "混合", "增强"],
            "kalman": ["kalman", "卡尔曼", "状态估计"],
        }
        for method_id, words in aliases.items():
            if any(word in lowered for word in words):
                selected.append(method_id)
        return list(dict.fromkeys(selected))

    def _wants_append_preprocess(self, text: str) -> bool:
        lowered = text.lower()
        return any(word in lowered for word in [
            "再加", "加上", "加入", "新增", "追加", "再用", "再使用", "同时用", "同时使用",
            "also", "add", "append",
        ])

    def _should_ask_preprocess_method(
        self,
        state: ConversationState,
        text: str,
        requested_methods: list[str],
        wants_comparison: bool,
    ) -> bool:
        if state.pending_preprocess_request and (requested_methods or wants_comparison):
            return False
        explicit_default = any(word in text.lower() for word in ["默认", "自动", "推荐"])
        return not requested_methods and not wants_comparison and not explicit_default

    def _preprocess_method_prompt(self) -> str:
        methods = "\n".join(
            f"- {item['label']}：{item['description']}"
            for item in list_preprocess_methods()
        )
        return (
            "检测到你要做噪声预处理。为了让处理过程可解释，请选择一种方法，"
            "也可以要求我比较多种方法。\n"
            f"{methods}\n"
            "你可以回复“用中值滤波并分析”、“用 FFT 低通 截止 30Hz”或“比较全部预处理方法”。"
        )

    def _help(self) -> str:
        return (
            "我是随机信号分析智能体，可以通过对话调用工具链。\n"
            "可用指令示例：\n"
            "1. 自主采集一段适合预处理实验的随机信号。\n"
            "2. 采集一段 8 秒、200Hz、主频 8Hz 的正弦信号加高斯噪声。\n"
            "3. 对当前信号做预处理，平滑窗口 9。\n"
            "4. 分析时域和频域特征。\n"
            "5. 解释结果并给出控制建议。\n"
            "也可以上传 CSV/TXT 信号文件后让我分析。"
        )

    def _acquire(self, state: ConversationState, text: str, suppress_next_hint: bool = False) -> str:
        plan = self._build_acquisition_plan_from_text(text)
        config = plan.config
        config = SignalConfig(
            sample_rate=float(config.sample_rate),
            duration=float(config.duration),
            base_frequency=float(config.base_frequency),
            amplitude=float(config.amplitude),
            noise_std=float(config.noise_std),
            ar_coefficient=float(config.ar_coefficient),
            impulse_probability=float(config.impulse_probability),
            seed=int(config.seed),
            signal_model=f"{config.waveform}+{config.noise_model}",
            waveform=config.waveform,
            noise_model=config.noise_model,
        )
        plan.config = config
        state.diagnostic_lab = {}
        state.bundle = acquire_with_plan(plan)
        state.processed = None
        state.summary = None
        state.decision = None
        state.preprocess_results = {}
        state.preprocess_comparison = None
        state.pending_preprocess_request = None
        state.audio_result = None
        state.acquisition_plan = plan.to_dict()
        state.acquisition_history.append(plan.to_dict())
        state.acquisition_history = state.acquisition_history[-8:]
        model_label = f"{self._waveform_label(config.waveform)} + {self._noise_model_label(config.noise_model)}"
        if plan.channel.autonomous:
            prefix = (
                f"已通过“{plan.channel.label}”自主采集{model_label}："
                f"{plan.policy}。"
            )
        else:
            prefix = f"已通过“{plan.channel.label}”采集{model_label}："
        answer = (
            f"{prefix}采样率 {config.sample_rate:.1f} Hz，"
            f"时长 {config.duration:.1f} s，样本数 {config.sample_count}，"
            f"目标主频 {config.base_frequency:.2f} Hz，随机种子 {config.seed}。"
        )
        if not suppress_next_hint:
            answer += "下一步可以说“预处理并分析”。"
        return answer

    def _ensure_realtime_stopped(self, state: ConversationState) -> str:
        plan = state.acquisition_plan or {}
        if state.bundle is None or plan.get("channel") != "realtime_stream" or plan.get("realtime_stopped"):
            return ""
        return self._stop_realtime_state(state, int(state.bundle.observed.size))

    def _build_acquisition_plan_from_text(self, text: str) -> AcquisitionPlan:
        seed = self._extract_seed(text)
        wants_autonomous = self._wants_autonomous_acquisition(text)
        channel_id = self._acquisition_channel_from_text(text, wants_autonomous)
        explicit_waveform = self._has_explicit_waveform(text)
        explicit_noise = self._has_explicit_noise_model(text)

        if wants_autonomous and not (explicit_waveform or explicit_noise):
            preset = self._autonomous_acquisition_preset(text, seed)
            waveform = preset["waveform"]
            noise_model = preset["noise_model"]
            default_frequency = float(preset["base_frequency"])
            default_duration = float(preset["duration"])
            default_noise = float(preset["noise_std"])
            policy = str(preset["policy"])
            goal = str(preset["goal"])
        else:
            waveform = self._waveform_from_text(text)
            noise_model = self._noise_model_from_text(text)
            default_frequency = 8.0
            default_duration = 60.0 if channel_id == "realtime_stream" else 8.0
            default_noise = 0.55
            if wants_autonomous:
                policy = "用户给定信号/噪声模型，智能体负责选择采集通道和采样配置"
                goal = self._acquisition_goal_from_text(text)
            else:
                policy = "按用户指定参数采集"
                goal = "manual_specified"

        frequency = self._extract_frequency(text, default=default_frequency)
        duration = self._extract_duration(text, default=default_duration)
        sample_rate = self._extract_sample_rate(text, default=200.0)
        if not self._has_explicit_sample_rate(text):
            sample_rate = max(sample_rate, frequency * 3.0, frequency * 2.0 + 20.0)
        elif frequency >= sample_rate * 0.48:
            sample_rate = max(sample_rate, frequency * 2.5)
        noise = self._number_after(text, ["噪声", "noise"], default=default_noise)
        max_duration = 120.0 if channel_id == "realtime_stream" else 60.0

        config = SignalConfig(
            sample_rate=float(min(max(sample_rate, 20.0), 20000.0)),
            duration=float(min(max(duration, 0.5), max_duration)),
            base_frequency=float(min(max(frequency, 0.1), max(sample_rate * 0.45, 0.1))),
            noise_std=float(min(max(noise or default_noise, 0.0), 10.0)),
            seed=seed,
            signal_model=f"{waveform}+{noise_model}",
            waveform=waveform,
            noise_model=noise_model,
        )
        candidates = self._candidate_acquisition_channels(text, channel_id, wants_autonomous)
        return build_acquisition_plan(
            config=config,
            channel_id=channel_id,
            goal=goal,
            policy=policy,
            candidate_channels=candidates,
        )

    def _wants_autonomous_acquisition(self, text: str) -> bool:
        lowered = text.lower()
        return any(
            word in lowered
            for word in [
                "自主",
                "自动",
                "智能采集",
                "自动采集",
                "自动巡检",
                "巡检",
                "多通道",
                "多渠道",
                "多源",
                "自己选",
                "自主选择",
                "无人值守",
                "autonomous",
                "auto",
                "multi-channel",
                "multichannel",
            ]
        )

    def _acquisition_channel_from_text(self, text: str, wants_autonomous: bool = False) -> str:
        lowered = text.lower()
        if "sensor_gateway" in lowered:
            return "sensor_gateway"
        if "realtime_stream" in lowered:
            return "realtime_stream"
        if "autonomous_sweep" in lowered:
            return "autonomous_sweep"
        if "simulated_lab" in lowered:
            return "simulated_lab"
        if any(word in lowered for word in ["sensor_gateway", "传感器", "硬件", "设备", "网关", "iot"]):
            return "sensor_gateway"
        if any(word in lowered for word in ["realtime_stream", "实时", "流式", "在线", "stream"]):
            return "realtime_stream"
        if any(word in lowered for word in ["autonomous_sweep", "自主巡检", "自动巡检", "巡检"]):
            return "autonomous_sweep"
        if wants_autonomous:
            return "autonomous_sweep"
        return "simulated_lab"

    def _candidate_acquisition_channels(self, text: str, selected_channel: str, wants_autonomous: bool) -> list[str]:
        lowered = text.lower()
        if wants_autonomous or any(word in lowered for word in ["多通道", "多渠道", "multi-channel", "multichannel"]):
            candidates = ["simulated_lab", "realtime_stream", "autonomous_sweep", "sensor_gateway"]
        else:
            candidates = [selected_channel]
        return list(dict.fromkeys([selected_channel, *candidates]))

    def _autonomous_acquisition_preset(self, text: str, seed: int) -> dict[str, Any]:
        lowered = text.lower()
        presets = [
            {
                "goal": "preprocess_benchmark",
                "waveform": "multi_sine",
                "noise_model": "gaussian_impulse",
                "base_frequency": 9.0,
                "duration": 10.0,
                "noise_std": 0.68,
                "policy": "面向预处理对比，选择多频正弦叠加高斯白噪声和脉冲干扰",
            },
            {
                "goal": "nonstationary_tracking",
                "waveform": "chirp",
                "noise_model": "ar",
                "base_frequency": 7.0,
                "duration": 9.0,
                "noise_std": 0.46,
                "policy": "面向非平稳随机过程，选择线性调频信号叠加 AR 相关噪声",
            },
            {
                "goal": "impulse_robustness",
                "waveform": "square",
                "noise_model": "impulse",
                "base_frequency": 6.0,
                "duration": 8.0,
                "noise_std": 0.42,
                "policy": "面向异常点和脉冲干扰鲁棒性，选择方波信号叠加脉冲干扰",
            },
            {
                "goal": "spectral_identification",
                "waveform": "sine",
                "noise_model": "gaussian",
                "base_frequency": 12.0,
                "duration": 8.0,
                "noise_std": 0.40,
                "policy": "面向频域主频识别，选择正弦信号叠加高斯白噪声",
            },
            {
                "goal": "colored_noise_process",
                "waveform": "random_process",
                "noise_model": "ar",
                "base_frequency": 8.0,
                "duration": 10.0,
                "noise_std": 0.55,
                "policy": "面向随机过程相关性分析，选择随机过程信号叠加有色 AR 噪声",
            },
        ]
        if any(word in lowered for word in ["预处理", "去噪", "滤波", "比较", "复杂噪声"]):
            return presets[0]
        if any(word in lowered for word in ["非平稳", "扫频", "调频", "跟踪", "漂移", "预测"]):
            return presets[1]
        if any(word in lowered for word in ["脉冲", "异常", "冲击", "突发"]):
            return presets[2]
        if any(word in lowered for word in ["频域", "功率谱", "主频", "fft", "谱"]):
            return presets[3]
        if any(word in lowered for word in ["相关", "有色", "ar", "自相关"]):
            return presets[4]
        return presets[seed % len(presets)]

    def _acquisition_goal_from_text(self, text: str) -> str:
        lowered = text.lower()
        if any(word in lowered for word in ["预处理", "去噪", "滤波", "比较"]):
            return "preprocess_benchmark"
        if any(word in lowered for word in ["非平稳", "扫频", "调频", "跟踪", "预测"]):
            return "nonstationary_tracking"
        if any(word in lowered for word in ["频域", "功率谱", "主频", "fft"]):
            return "spectral_identification"
        if any(word in lowered for word in ["脉冲", "异常", "冲击"]):
            return "impulse_robustness"
        return "general_random_signal_acquisition"

    def _has_explicit_waveform(self, text: str) -> bool:
        lowered = text.lower()
        return any(
            word in lowered
            for word in [
                "正弦",
                "方波",
                "三角波",
                "锯齿波",
                "多频",
                "多正弦",
                "线性调频",
                "扫频",
                "sine",
                "square",
                "triangle",
                "sawtooth",
                "chirp",
                "multi_sine",
            ]
        )

    def _has_explicit_noise_model(self, text: str) -> bool:
        lowered = text.lower()
        return any(
            word in lowered
            for word in [
                "高斯",
                "白噪声",
                "均匀",
                "脉冲",
                "冲击",
                "相关噪声",
                "有色噪声",
                "色噪声",
                "gaussian",
                "uniform",
                "impulse",
                "colored",
                "white noise",
            ]
        )

    def _preprocess(
        self,
        state: ConversationState,
        text: str,
        methods: str | list[str] | None = None,
        optimization_mode: str = "manual",
    ) -> str:
        if state.bundle is None:
            self._acquire(state, text)
        if state.bundle is None:
            return "当前没有信号，请先采集或上传信号文件。"
        stop_note = self._ensure_realtime_stopped(state)
        requested = methods
        if requested is None:
            extracted = self._extract_preprocess_methods(text)
            requested = extracted[0] if extracted else "robust_mean"
        if isinstance(requested, list):
            requested_methods = [normalize_preprocess_method(method) for method in requested]
        else:
            requested_methods = [normalize_preprocess_method(requested)]
        requested_methods = list(dict.fromkeys(requested_methods))
        if self._wants_append_preprocess(text) and state.preprocess_results:
            requested_methods = list(dict.fromkeys(list(state.preprocess_results.keys()) + requested_methods))

        if len(requested_methods) > 1:
            result = self._compare_preprocess_methods(state, requested_methods, text, optimization_mode)
            return f"{stop_note}\n{result}".strip() if stop_note else result

        method = requested_methods[0]
        cfg = self._preprocess_config_for_method(state, text, method)
        state.processed = preprocess_signal(state.bundle.observed, cfg)
        state.preprocess_results = {method: state.processed}
        state.preprocess_comparison = None
        state.summary = None
        state.decision = None
        state.pending_preprocess_request = None
        anomaly_count = int(state.processed.anomaly_mask.sum())
        sigma = cfg.anomaly_threshold_sigma
        result = (
            f"预处理完成：已使用“{state.processed.method_label}”。"
            f"窗口 {state.processed.smoothing_window}，异常点阈值 {sigma:.1f}σ，"
            f"检测到 {anomaly_count} 个异常点。\n"
            f"方法说明：{PREPROCESS_METHODS[method]['description']}"
        )
        return f"{stop_note}\n{result}".strip() if stop_note else result

    def _compare_preprocess_methods(
        self,
        state: ConversationState,
        methods: list[str],
        text: str = "",
        optimization_mode: str = "manual",
    ) -> str:
        assert state.bundle is not None
        results: dict[str, Any] = {}
        comparison_rows: list[dict[str, Any]] = []
        best_method: str | None = None
        best_score = float("-inf")

        for method in methods:
            method = normalize_preprocess_method(method)
            method_started = perf_counter()
            emit_progress(method, "running")
            processed, summary, score, searched = self._best_preprocess_candidate(
                state,
                text,
                method,
                optimization_mode,
            )
            quality = summary["quality"]
            freq = summary["frequency_features"]
            time_features = summary["time_features"]
            quality_details = self._preprocess_quality_details(state, processed, summary)
            elapsed_ms = round((perf_counter() - method_started) * 1000, 2)
            emit_progress(method, "success", duration_ms=elapsed_ms)
            if score > best_score:
                best_score = score
                best_method = processed.method
            results[processed.method] = processed
            comparison_rows.append(
                {
                    "method": processed.method,
                    "label": processed.method_label,
                    "description": PREPROCESS_METHODS[processed.method]["description"],
                    "rms": time_features["rms"],
                    "dominant_frequency_hz": freq["dominant_frequency_hz"],
                    "spectral_entropy": freq["spectral_entropy"],
                    "spectral_bandwidth_hz": freq["spectral_bandwidth_hz"],
                    "processed_snr_db": quality["processed_snr_db"],
                    "snr_improvement_db": quality["snr_improvement_db"],
                    "anomaly_rate": quality["anomaly_rate"],
                    "detected_anomaly_count": quality["detected_anomaly_count"],
                    "roughness_reduction": quality_details["roughness_reduction"],
                    "rmse_reduction": quality_details["rmse_reduction"],
                    "residual_correlation": quality_details["residual_correlation"],
                    "clean_correlation": quality_details["clean_correlation"],
                    "parameters": processed.parameters,
                    "candidate_count": searched,
                    "optimization_mode": optimization_mode,
                    "score": round(score, 3),
                    "score_terms": self._preprocess_score_terms(state, summary, processed),
                    "duration_ms": elapsed_ms,
                    "rms_ratio_error": quality_details["rms_ratio_error"],
                }
            )

        assert best_method is not None
        state.preprocess_results = results
        state.processed = results[best_method]
        state.summary = self._summarize_processed(state, state.processed)
        state.decision = self._decide(state)
        state.pending_preprocess_request = None
        state.preprocess_comparison = {
            "recommended": best_method,
            "recommended_label": state.processed.method_label,
            "goal": state.comparison_goal,
            "reference_mode": "clean_reference" if state.bundle.has_clean_reference else "no_reference",
            "score_version": "0.2.0",
            "score_note": "相同数据与目标下的相对评分；无参考评分仅为启发式诊断，不代表真实去噪质量。",
            "optimization_mode": optimization_mode,
            "methods": sorted(comparison_rows, key=lambda item: item["score"], reverse=True),
        }

        if optimization_mode == "autonomous":
            lines = [
                "已完成 Agent 自主预处理寻优：每种方法不依赖右侧预设参数，而是在更宽参数空间内先搜索各自最优参数，再做方法间比较。",
                f"推荐方法：{state.processed.method_label}。",
            ]
        else:
            lines = [
                "已完成多种预处理方法比较：每种方法先围绕工具库参数搜索候选参数，再比较各方法最优参数下的综合得分。",
                f"推荐方法：{state.processed.method_label}。",
            ]
        for row in state.preprocess_comparison["methods"]:
            snr_text = "未计算" if row["processed_snr_db"] is None else f"{row['processed_snr_db']:.2f} dB"
            params_text = self._format_agent_parameters(row.get("parameters"))
            lines.append(
                f"- {row['label']}：SNR={snr_text}，谱熵={row['spectral_entropy']:.3f}，"
                f"主频={row['dominant_frequency_hz']:.2f} Hz，得分={row['score']:.3f}，"
                f"最优参数：{params_text}"
            )
        return "\n".join(lines)

    def _best_preprocess_candidate(
        self,
        state: ConversationState,
        text: str,
        method: str,
        optimization_mode: str = "manual",
    ) -> tuple[PreprocessResult, dict[str, Any], float, int]:
        best_processed: PreprocessResult | None = None
        best_summary: dict[str, Any] | None = None
        best_score = float("-inf")
        candidates = self._preprocess_parameter_candidates(state, text, method, optimization_mode)
        cap = max(1, min(LIMITS["candidates_per_method"], LIMITS["candidate_sample_budget"] // len(state.bundle.observed)))
        if len(candidates) > cap:
            candidates = [candidates[int(i)] for i in np.linspace(0, len(candidates) - 1, cap)]
        for config in candidates:
            check_cancelled()
            processed = preprocess_signal(state.bundle.observed, config)
            summary = self._candidate_preprocess_summary(state, processed)
            score = self._preprocess_quality_score(state, summary, processed)
            if score > best_score:
                best_score = score
                best_processed = processed
                best_summary = summary
        assert best_processed is not None
        assert best_summary is not None
        return best_processed, best_summary, best_score, len(candidates)

    def _candidate_preprocess_summary(
        self,
        state: ConversationState,
        processed: PreprocessResult,
    ) -> dict[str, Any]:
        assert state.bundle is not None
        time_features = extract_time_features(processed.signal)
        frequency_features = extract_frequency_features(
            processed.signal,
            state.bundle.config.sample_rate,
        )
        if state.bundle.has_clean_reference:
            raw_snr: float | None = estimate_snr(state.bundle.clean, state.bundle.observed)
            processed_snr: float | None = estimate_snr(state.bundle.clean, processed.signal)
            snr_improvement: float | None = processed_snr - raw_snr
        else:
            raw_snr = None
            processed_snr = None
            snr_improvement = None
        return {
            "time_features": time_features,
            "frequency_features": frequency_features,
            "quality": {
                "raw_snr_db": None if raw_snr is None else float(raw_snr),
                "processed_snr_db": None if processed_snr is None else float(processed_snr),
                "snr_improvement_db": None if snr_improvement is None else float(snr_improvement),
                "anomaly_rate": float(np.mean(processed.anomaly_mask)),
                "detected_anomaly_count": int(np.sum(processed.anomaly_mask)),
                "has_clean_reference": state.bundle.has_clean_reference,
            },
        }

    def _preprocess_quality_score(
        self,
        state: ConversationState,
        summary: dict[str, Any],
        processed: PreprocessResult,
    ) -> float:
        return sum(self._preprocess_score_terms(state, summary, processed).values())

    def _preprocess_score_terms(self, state, summary, processed) -> dict[str, float]:
        """Dimensionless, method-neutral terms; no-reference scores are heuristics."""
        d = self._preprocess_quality_details(state, processed, summary)
        goal = state.comparison_goal
        clip = lambda x: float(np.clip(x, -1, 1))
        if state.bundle.has_clean_reference:
            weights = {"denoise": (65, 25, 10), "waveform": (45, 45, 10), "transient": (35, 25, 40)}[goal]
            return {"rmse_reduction": weights[0] * clip(d["rmse_reduction"]),
                    "reference_correlation": weights[1] * clip(d["clean_correlation"]),
                    "reference_roughness_penalty": -weights[2] * min(d["clean_roughness_error"], 1)}
        weights = {"denoise": (40, 30, 30), "waveform": (15, 25, 60), "transient": (0, 20, 80)}[goal]
        terms = {"roughness_reduction": weights[0] * clip(d["roughness_reduction"]),
                 "residual_correlation_penalty": -weights[1] * abs(clip(d["residual_correlation"])),
                 "amplitude_change_penalty": -weights[2] * min(d["rms_ratio_error"], 1)}
        if goal == "transient":
            original = np.max(np.abs(state.bundle.observed)) + 1e-12
            terms["peak_change_penalty"] = -40 * min(abs(np.max(np.abs(processed.signal)) / original - 1), 1)
        return terms

    def _preprocess_quality_details(
        self,
        state: ConversationState,
        processed: PreprocessResult,
        summary: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        observed = state.bundle.observed if state.bundle is not None else processed.signal
        observed = np.asarray(observed, dtype=float)
        processed_signal = np.asarray(processed.signal, dtype=float)
        observed_rms = float(np.sqrt(np.mean(np.square(observed)))) + 1e-12
        processed_rms = float(np.sqrt(np.mean(np.square(processed_signal)))) + 1e-12
        observed_roughness = self._signal_roughness(observed)
        processed_roughness = self._signal_roughness(processed_signal)
        roughness_reduction = 0.0
        if observed_roughness > 1e-12:
            roughness_reduction = (observed_roughness - processed_roughness) / observed_roughness
        residual = observed - processed_signal
        details = {
            "roughness_reduction": float(roughness_reduction),
            "residual_correlation": float(self._safe_correlation(residual, processed_signal)),
            "rms_ratio_error": abs(float(np.log(max(processed_rms / observed_rms, 1e-6)))),
            "rmse_reduction": 0.0,
            "clean_correlation": 0.0,
            "clean_roughness_error": 0.0,
        }
        if state.bundle is not None and state.bundle.has_clean_reference:
            clean = np.asarray(state.bundle.clean, dtype=float)
            clean_rmse_raw = float(np.sqrt(np.mean(np.square(observed - clean)))) + 1e-12
            clean_rmse_processed = float(np.sqrt(np.mean(np.square(processed_signal - clean))))
            clean_roughness = self._signal_roughness(clean)
            details["rmse_reduction"] = float((clean_rmse_raw - clean_rmse_processed) / clean_rmse_raw)
            details["clean_correlation"] = float(self._safe_correlation(clean, processed_signal))
            details["clean_roughness_error"] = abs(float(np.log((processed_roughness + 1e-12) / (clean_roughness + 1e-12))))
        return details

    def _signal_roughness(self, signal: np.ndarray) -> float:
        values = np.asarray(signal, dtype=float)
        if values.size < 2:
            return 0.0
        return float(np.sqrt(np.mean(np.square(np.diff(values)))))

    def _safe_correlation(self, left: np.ndarray, right: np.ndarray) -> float:
        a = np.asarray(left, dtype=float)
        b = np.asarray(right, dtype=float)
        if a.size != b.size or a.size < 2:
            return 0.0
        a_std = float(np.std(a))
        b_std = float(np.std(b))
        if a_std <= 1e-12 or b_std <= 1e-12:
            return 0.0
        return float(np.corrcoef(a, b)[0, 1])

    def _preprocess_parameter_candidates(
        self,
        state: ConversationState,
        text: str,
        method: str,
        optimization_mode: str = "manual",
    ) -> list[PreprocessConfig]:
        base = self._preprocess_config_for_method(state, text, method)
        sample_rate = float(state.bundle.config.sample_rate)
        method = normalize_preprocess_method(method)

        def odd_window(value: int) -> int:
            value = int(min(max(value, 1), 31))
            if value % 2 == 0:
                value += 1 if value < 31 else -1
            return int(min(max(value, 1), 31))

        def unique(values: list[float], digits: int = 6) -> list[float]:
            output: list[float] = []
            seen: set[float] = set()
            for value in values:
                key = round(float(value), digits)
                if key not in seen:
                    seen.add(key)
                    output.append(float(value))
            return output

        if optimization_mode == "autonomous":
            return self._autonomous_preprocess_parameter_candidates(
                state,
                base,
                method,
                odd_window,
                unique,
            )

        sigma_values = unique([
            max(1.5, min(6.0, base.anomaly_threshold_sigma - 0.5)),
            max(1.5, min(6.0, base.anomaly_threshold_sigma)),
            max(1.5, min(6.0, base.anomaly_threshold_sigma + 0.5)),
        ], digits=3)
        windows = [odd_window(value) for value in [
            base.smoothing_window - 4,
            base.smoothing_window - 2,
            base.smoothing_window,
            base.smoothing_window + 2,
            base.smoothing_window + 4,
        ]]
        windows = list(dict.fromkeys(windows))

        candidates: list[PreprocessConfig] = []
        if method in {"robust_mean", "median", "hybrid"}:
            for window in windows:
                for sigma in sigma_values:
                    candidates.append(self._clone_preprocess_config(base, smoothing_window=window, anomaly_threshold_sigma=sigma))
        elif method == "ema":
            alpha_values = unique([
                max(0.02, min(0.95, base.ema_alpha * 0.5)),
                max(0.02, min(0.95, base.ema_alpha * 0.75)),
                max(0.02, min(0.95, base.ema_alpha)),
                max(0.02, min(0.95, base.ema_alpha * 1.25)),
                max(0.02, min(0.95, base.ema_alpha * 1.5)),
            ], digits=4)
            for alpha in alpha_values:
                for sigma in sigma_values:
                    candidates.append(self._clone_preprocess_config(base, ema_alpha=alpha, anomaly_threshold_sigma=sigma))
        elif method == "fft_lowpass":
            default_cutoff = base.lowpass_cutoff_hz or max(sample_rate * 0.18, 1.0)
            max_cutoff = max(0.1, sample_rate / 2.0)
            cutoff_values = unique([
                max(0.1, min(max_cutoff, default_cutoff * 0.5)),
                max(0.1, min(max_cutoff, default_cutoff * 0.75)),
                max(0.1, min(max_cutoff, default_cutoff)),
                max(0.1, min(max_cutoff, default_cutoff * 1.25)),
                max(0.1, min(max_cutoff, default_cutoff * 1.5)),
            ], digits=3)
            for cutoff in cutoff_values:
                for sigma in sigma_values:
                    candidates.append(self._clone_preprocess_config(base, lowpass_cutoff_hz=cutoff, anomaly_threshold_sigma=sigma))
        elif method == "kalman":
            q_values = unique([
                max(0.001, min(1.0, base.kalman_process_noise * 0.5)),
                max(0.001, min(1.0, base.kalman_process_noise)),
                max(0.001, min(1.0, base.kalman_process_noise * 2.0)),
            ], digits=6)
            r_values = unique([
                max(0.001, min(3.0, base.kalman_measurement_noise * 0.5)),
                max(0.001, min(3.0, base.kalman_measurement_noise)),
                max(0.001, min(3.0, base.kalman_measurement_noise * 2.0)),
            ], digits=6)
            for q in q_values:
                for r in r_values:
                    candidates.append(self._clone_preprocess_config(base, kalman_process_noise=q, kalman_measurement_noise=r))
        else:
            candidates.append(base)
        return candidates or [base]

    def _autonomous_preprocess_parameter_candidates(
        self,
        state: ConversationState,
        base: PreprocessConfig,
        method: str,
        odd_window: Any,
        unique: Any,
    ) -> list[PreprocessConfig]:
        assert state.bundle is not None
        sample_rate = float(state.bundle.config.sample_rate)
        sample_count = int(state.bundle.observed.size)
        nyquist = max(0.1, sample_rate / 2.0)
        method = normalize_preprocess_method(method)

        max_window = max(3, min(81, sample_count // 6 if sample_count >= 18 else sample_count))
        if max_window % 2 == 0:
            max_window -= 1
        window_values = [
            3,
            5,
            7,
            9,
            11,
            15,
            21,
            31,
            41,
            61,
            max_window,
        ]
        windows = list(dict.fromkeys(
            odd_window(value)
            for value in window_values
            if 1 <= value <= max_window
        ))
        sigma_values = unique([1.5, 2.0, 2.5, 3.0, 3.5, 4.5, 6.0], digits=3)
        candidates: list[PreprocessConfig] = []

        if method in {"robust_mean", "median"}:
            for window in windows:
                for sigma in sigma_values:
                    candidates.append(self._clone_preprocess_config(
                        base,
                        smoothing_window=window,
                        anomaly_threshold_sigma=sigma,
                    ))
            return candidates or [base]

        if method == "hybrid":
            raw_freq = extract_frequency_features(state.bundle.observed, sample_rate)
            dominant = float(raw_freq.get("dominant_frequency_hz") or state.bundle.config.base_frequency or 0.0)
            cutoff_values: list[float | None] = [None]
            if dominant > 0:
                cutoff_values.extend([
                    max(0.1, min(nyquist, dominant * ratio))
                    for ratio in [1.2, 1.5, 2.0, 2.8, 4.0]
                ])
            cutoff_values.extend([
                max(0.1, min(nyquist, sample_rate * ratio))
                for ratio in [0.05, 0.08, 0.12, 0.18]
            ])
            numeric_cutoffs = unique([value for value in cutoff_values if value is not None], digits=3)
            cutoff_candidates: list[float | None] = [None] + numeric_cutoffs
            for window in windows:
                for sigma in sigma_values:
                    for cutoff in cutoff_candidates:
                        candidates.append(self._clone_preprocess_config(
                            base,
                            smoothing_window=window,
                            anomaly_threshold_sigma=sigma,
                            lowpass_cutoff_hz=cutoff,
                        ))
            return candidates or [base]

        if method == "ema":
            alpha_values = unique([0.04, 0.07, 0.1, 0.16, 0.22, 0.32, 0.45, 0.62, 0.78, 0.9], digits=4)
            for alpha in alpha_values:
                for sigma in sigma_values:
                    candidates.append(self._clone_preprocess_config(
                        base,
                        ema_alpha=alpha,
                        anomaly_threshold_sigma=sigma,
                    ))
            return candidates or [base]

        if method == "fft_lowpass":
            raw_freq = extract_frequency_features(state.bundle.observed, sample_rate)
            dominant = float(raw_freq.get("dominant_frequency_hz") or state.bundle.config.base_frequency or 0.0)
            rolloff = float(raw_freq.get("spectral_rolloff_85_hz") or 0.0)
            anchors = [
                sample_rate * ratio
                for ratio in [0.03, 0.05, 0.08, 0.12, 0.18, 0.25, 0.35, 0.45]
            ]
            if dominant > 0:
                anchors.extend([dominant * ratio for ratio in [1.2, 1.5, 2.0, 3.0, 4.0, 6.0]])
            if rolloff > 0:
                anchors.extend([rolloff * ratio for ratio in [0.65, 0.85, 1.0, 1.2]])
            cutoff_values = unique([
                max(0.1, min(nyquist, value))
                for value in anchors
                if value > 0.0
            ], digits=3)
            for cutoff in cutoff_values:
                for sigma in sigma_values:
                    candidates.append(self._clone_preprocess_config(
                        base,
                        lowpass_cutoff_hz=cutoff,
                        anomaly_threshold_sigma=sigma,
                    ))
            return candidates or [base]

        if method == "kalman":
            q_values = unique([0.001, 0.003, 0.01, 0.03, 0.08, 0.16, 0.32, 0.65], digits=6)
            r_values = unique([0.01, 0.03, 0.08, 0.16, 0.32, 0.65, 1.2, 2.4], digits=6)
            p_values = unique([0.1, 0.5, 1.0, 2.0, 5.0], digits=6)
            for q in q_values:
                for r in r_values:
                    for p in p_values:
                        for sigma in sigma_values:
                            candidates.append(self._clone_preprocess_config(
                                base,
                                kalman_process_noise=q,
                                kalman_measurement_noise=r,
                                kalman_initial_error=p,
                                anomaly_threshold_sigma=sigma,
                            ))
            return candidates or [base]

        return [base]

    def _clone_preprocess_config(self, base: PreprocessConfig, **updates: Any) -> PreprocessConfig:
        values = {
            "smoothing_window": base.smoothing_window,
            "anomaly_threshold_sigma": base.anomaly_threshold_sigma,
            "repair_impulses": base.repair_impulses,
            "remove_mean": base.remove_mean,
            "method": base.method,
            "lowpass_cutoff_hz": base.lowpass_cutoff_hz,
            "sample_rate": base.sample_rate,
            "ema_alpha": base.ema_alpha,
            "kalman_process_noise": base.kalman_process_noise,
            "kalman_measurement_noise": base.kalman_measurement_noise,
            "kalman_initial_error": base.kalman_initial_error,
        }
        values.update(updates)
        return PreprocessConfig(**values)

    def _preprocess_config_for_method(
        self,
        state: ConversationState,
        text: str,
        method: str,
    ) -> PreprocessConfig:
        assert state.bundle is not None
        method = normalize_preprocess_method(method)
        library_params = state.tool_library.get(method, {})
        default_window = int(library_params.get("smoothing_window", 7))
        default_sigma = float(library_params.get("anomaly_threshold_sigma", 3.0))
        default_cutoff = float(library_params.get("lowpass_cutoff_hz", 0.0))
        default_alpha = float(library_params.get("ema_alpha", 0.22))
        default_kalman_q = float(library_params.get("kalman_process_noise", 0.02))
        default_kalman_r = float(library_params.get("kalman_measurement_noise", 0.25))
        default_kalman_p = float(library_params.get("kalman_initial_error", 1.0))

        window = int(self._number_after(text, ["窗口", "window", "平滑"], default=default_window))
        if window % 2 == 0:
            window += 1
        sigma = self._number_after(text, ["阈值", "sigma"], default=default_sigma)
        cutoff = self._number_after(text, ["截止频率", "截止", "cutoff", "低通"], default=default_cutoff)
        alpha = self._number_after(text, ["alpha", "系数"], default=default_alpha)
        kalman_q = self._number_after(text, ["过程噪声", "process_noise", "process", "Q"], default=default_kalman_q)
        kalman_r = self._number_after(text, ["测量噪声", "measurement_noise", "measurement", "R"], default=default_kalman_r)
        kalman_p = self._number_after(text, ["初始误差", "initial_error", "initial", "P"], default=default_kalman_p)
        return PreprocessConfig(
            smoothing_window=window,
            anomaly_threshold_sigma=float(sigma),
            lowpass_cutoff_hz=None if cutoff <= 0 else float(cutoff),
            sample_rate=float(state.bundle.config.sample_rate),
            ema_alpha=float(alpha),
            kalman_process_noise=float(kalman_q),
            kalman_measurement_noise=float(kalman_r),
            kalman_initial_error=float(kalman_p),
            method=method,
        )

    def _analyze(self, state: ConversationState, text: str = "") -> str:
        if state.bundle is None:
            return "当前没有信号，请先采集或上传信号文件。"
        stop_note = self._ensure_realtime_stopped(state)
        if state.processed is None:
            state.summary = self._summarize_observed(state)
        else:
            state.summary = self._summarize_processed(state, state.processed)
        state.decision = self._decide(state)

        time_features = state.summary["time_features"]
        freq = state.summary["frequency_features"]
        quality = state.summary["quality"]
        snr_text = (
            "无干净参考，未计算真实 SNR"
            if quality["processed_snr_db"] is None
            else f"{quality['processed_snr_db']:.2f} dB"
        )
        if self._wants_domain_table(text):
            result = f"分析完成。\n{self._series_feature_report(state, text)}"
            return f"{stop_note}\n{result}".strip() if stop_note else result
        result = (
            "分析完成。\n"
            f"- 时域：RMS={time_features['rms']:.3f}，方差={time_features['variance']:.3f}，"
            f"一阶自相关={time_features['lag1_autocorrelation']:.3f}\n"
            f"- 频域：主频={freq['dominant_frequency_hz']:.2f} Hz，"
            f"谱熵={freq['spectral_entropy']:.3f}，谱带宽={freq['spectral_bandwidth_hz']:.2f} Hz\n"
            f"- 高级随机过程：AR({state.summary['advanced_analysis']['ar_model']['order']})，"
            f"相关长度={state.summary['advanced_analysis']['autocorrelation']['correlation_length_lag']} lag，"
            f"残差白化分数={state.summary['advanced_analysis']['prediction_residual']['whiteness_score']:.3f}\n"
            f"- 质量：SNR={snr_text}，异常点率={quality['anomaly_rate'] * 100:.2f}%\n"
            f"- 决策：{state.decision['status']}，{state.decision['filter_level']}"
        )
        return f"{stop_note}\n{result}".strip() if stop_note else result

    def _explain(self, state: ConversationState) -> str:
        if state.last_intent == "knowledge" or state.last_knowledge_topic:
            knowledge_text = state.last_knowledge_question or state.last_knowledge_topic or "该知识点"
            return self._answer_signal_knowledge(state, knowledge_text)
        if state.bundle is None:
            return "当前还没有信号结果可解释。请先采集或上传信号，再执行预处理/分析。"
        if state.summary is None:
            return self._analyze(state)
        assert state.summary is not None
        assert state.decision is not None
        freq = state.summary["frequency_features"]
        time_features = state.summary["time_features"]
        quality = state.summary["quality"]
        actions = "\n".join(f"- {item}" for item in state.decision["recommended_actions"])
        return (
            "结果解释：\n"
            f"主频 {freq['dominant_frequency_hz']:.2f} Hz 表示当前信号能量主要集中在该频率附近；"
            f"谱熵 {freq['spectral_entropy']:.3f} 用于衡量频谱分散程度；"
            f"一阶自相关 {time_features['lag1_autocorrelation']:.3f} 表示相邻采样点具有较强时间相关性。"
            f"异常点率为 {quality['anomaly_rate'] * 100:.2f}%。\n"
            f"建议：\n{actions}"
        )

    def _status(self, state: ConversationState) -> str:
        if state.bundle is None:
            return "当前会话还没有信号。你可以采集模拟信号，或上传 CSV/TXT 文件。"
        summary = (
            "已完成分析"
            if state.summary is not None
            else ("已完成预处理" if state.processed is not None else "已采集信号")
        )
        return (
            f"当前状态：{summary}。样本数 {state.bundle.observed.size}，"
            f"采样率 {state.bundle.config.sample_rate:.2f} Hz，来源 {state.bundle.source}。"
            f"采集通道：{(state.acquisition_plan or {}).get('channel_label', '未记录')}。"
        )

    def _fallback(self, state: ConversationState) -> str:
        if state.bundle is None:
            return "我还没有信号数据。你可以说“采集一段随机信号”，或先上传 CSV/TXT 文件。"
        return "我可以继续执行：预处理、时域分析、频域分析、解释结果。你可以直接说“预处理并分析”。"

    def _decide(self, state: ConversationState) -> dict[str, Any]:
        assert state.summary is not None
        quality = state.summary["quality"]
        time_features = state.summary["time_features"]
        freq = state.summary["frequency_features"]
        snr = quality["processed_snr_db"]
        anomaly_rate = quality["anomaly_rate"]
        entropy = freq["spectral_entropy"]
        actions: list[str] = []

        if snr is None:
            status = "已分析"
            level = "自适应滤波"
            actions.append("上传信号缺少干净参考，建议结合静默段或历史基线估计噪声功率")
        elif snr < 3:
            status = "噪声占优"
            level = "强滤波"
            actions.append("扩大平滑窗口，并延长采样窗口")
        elif snr < 8:
            status = "可用但需抑噪"
            level = "中等滤波"
            actions.append("保持鲁棒异常点抑制，并使用 7-9 点平滑窗口")
        else:
            status = "稳定"
            level = "轻滤波"
            actions.append("降低平滑强度，保留瞬态细节")

        if anomaly_rate > 0.015:
            actions.append("异常点率偏高，建议检查脉冲干扰或采集线路")
        if entropy > 0.55:
            actions.append("谱熵偏高，说明宽带噪声或多频成分较明显")
        if time_features["lag1_autocorrelation"] > 0.85:
            actions.append("时间相关性强，可引入 AR 模型或卡尔曼滤波预测")

        return {
            "status": status,
            "filter_level": level,
            "recommended_actions": actions,
            "control_parameters": {
                "next_smoothing_window": 9 if snr is None else (13 if snr < 3 else (9 if snr < 8 else 5)),
                "track_frequency_hz": freq["dominant_frequency_hz"],
            },
        }

    def _risk_payload(self, state: ConversationState) -> dict[str, Any]:
        if state.summary is None or state.decision is None:
            return {"level": "idle", "score": 0, "reasons": []}
        quality = state.summary["quality"]
        freq = state.summary["frequency_features"]
        snr = quality["processed_snr_db"]
        anomaly_rate = quality["anomaly_rate"]
        entropy = freq["spectral_entropy"]
        score = 0.0
        reasons: list[str] = []

        if snr is not None:
            if snr < 3:
                score += 42
                reasons.append("SNR 低于 3 dB")
            elif snr < 8:
                score += 22
                reasons.append("SNR 处于中等水平")
        if anomaly_rate > 0.015:
            score += 25
            reasons.append("脉冲异常点比例偏高")
        if entropy > 0.55:
            score += 24
            reasons.append("谱熵偏高，频谱较分散")
        if freq["spectral_bandwidth_hz"] > 12:
            score += 12
            reasons.append("谱带宽较大")

        if score >= 55:
            level = "high"
        elif score >= 25:
            level = "medium"
        else:
            level = "low"
        return {
            "level": level,
            "score": round(min(score, 100), 1),
            "reasons": reasons or ["信号质量处于可控范围"],
        }

    def _build_insights(self, state: ConversationState) -> list[dict[str, str]]:
        if state.summary is None:
            return []
        selected_summary = state.summary
        return self._insights_from_summary(selected_summary)

    def _insights_from_summary(self, summary: dict[str, Any]) -> list[dict[str, str]]:
        tf = summary["time_features"]
        ff = summary["frequency_features"]
        quality = summary["quality"]
        advanced = summary.get("advanced_analysis") or {}
        ar = advanced.get("ar_model") or {}
        autocorr = advanced.get("autocorrelation") or {}
        residual = advanced.get("prediction_residual") or {}
        snr_text = (
            "未计算"
            if quality["processed_snr_db"] is None
            else f"{quality['processed_snr_db']:.2f} dB"
        )
        return [
            {
                "label": "随机过程统计量",
                "value": f"方差 {tf['variance']:.3f}, RMS {tf['rms']:.3f}",
                "meaning": "刻画随机信号能量和波动强度",
            },
            {
                "label": "自相关分析",
                "value": f"ρ(1)={tf['lag1_autocorrelation']:.3f}",
                "meaning": "判断相邻采样点的时间依赖性",
            },
            {
                "label": "功率谱估计",
                "value": f"主频 {ff['dominant_frequency_hz']:.2f} Hz",
                "meaning": "定位主要频率成分",
            },
            {
                "label": "AR 模型",
                "value": f"AR({int(ar.get('order', 0))}) 残差方差 {float(ar.get('noise_variance', 0.0)):.4f}",
                "meaning": "用自回归模型刻画随机过程的短时记忆和可预测性",
            },
            {
                "label": "预测残差分析",
                "value": f"白化分数 {float(residual.get('whiteness_score', 0.0)):.3f}",
                "meaning": f"相关长度约 {int(autocorr.get('correlation_length_lag', 0))} 个采样间隔，残差越白表示模型解释越充分",
            },
            {
                "label": "谱熵",
                "value": f"{ff['spectral_entropy']:.3f}",
                "meaning": "衡量频谱分散程度和噪声占比",
            },
            {
                "label": "质量评估",
                "value": f"SNR {snr_text}",
                "meaning": "用于驱动滤波强度和告警决策",
            },
        ]

    def _default_series_key(self, state: ConversationState) -> str:
        if state.processed is None:
            return "observed"
        if state.preprocess_comparison is not None:
            return f"processed_{state.processed.method}"
        return "processed"

    def _series_payload(self, state: ConversationState) -> dict[str, list[float]]:
        assert state.bundle is not None
        arrays = [state.bundle.time, state.bundle.observed]
        names = ["time", "observed"]
        analysis_payload: dict[str, Any] = {
            "observed": self._analysis_for_series(
                state,
                "observed",
                "原始观测",
                state.bundle.observed,
                None,
            )
        }
        if state.processed is not None:
            arrays.append(state.processed.signal)
            names.append("processed")
            analysis_payload["processed"] = self._analysis_for_series(
                state,
                "processed",
                state.processed.method_label,
                state.processed.signal,
                state.processed,
            )
        comparison_series: list[dict[str, str]] = []
        if state.preprocess_comparison is not None:
            for item in state.preprocess_comparison.get("methods", []):
                method = item["method"]
                result = state.preprocess_results.get(method)
                if result is None:
                    continue
                name = f"processed_{method}"
                arrays.append(result.signal)
                names.append(name)
                comparison_series.append({
                    "key": name,
                    "method": method,
                    "label": item["label"],
                })
                analysis_payload[name] = self._analysis_for_series(
                    state,
                    name,
                    item["label"],
                    result.signal,
                    result,
                )
        if state.summary is not None:
            spectrum = state.summary["frequency_features"]["spectrum"]
            freq, power = decimate_for_export(
                spectrum["frequencies"],
                spectrum["power"],
                max_points=360,
            )
        else:
            observed_spectrum = analysis_payload["observed"]
            freq = observed_spectrum["frequency"]
            power = observed_spectrum["power"]

        values = decimate_for_export(*arrays, max_points=520)
        payload = {name: value for name, value in zip(names, values)}
        if comparison_series:
            payload["comparison_series"] = comparison_series
        payload["analysis"] = analysis_payload
        payload["frequency"] = freq
        payload["power"] = power
        return payload

    def _analysis_for_series(
        self,
        state: ConversationState,
        key: str,
        label: str,
        signal: Any,
        processed: PreprocessResult | None,
    ) -> dict[str, Any]:
        assert state.bundle is not None
        time_features = extract_time_features(signal)
        frequency_features = extract_frequency_features(signal, state.bundle.config.sample_rate)
        if processed is None:
            if state.bundle.has_clean_reference:
                raw_snr = float(estimate_snr(state.bundle.clean, signal))
            else:
                raw_snr = None
            anomaly_rate = float(state.bundle.impulse_mask.mean()) if state.bundle.impulse_mask.size else 0.0
            quality = {
                "raw_snr_db": raw_snr,
                "processed_snr_db": raw_snr,
                "snr_improvement_db": 0.0 if raw_snr is not None else None,
                "anomaly_rate": anomaly_rate,
                "detected_anomaly_count": int(state.bundle.impulse_mask.sum()),
                "has_clean_reference": state.bundle.has_clean_reference,
            }
        else:
            summary = self._summarize_processed(state, processed)
            quality = summary["quality"]
        spectrum = frequency_features["spectrum"]
        freq, power = decimate_for_export(
            spectrum["frequencies"],
            spectrum["power"],
            max_points=360,
        )
        summary_payload = {
            "time_features": time_features,
            "frequency_features": {
                item_key: item_value
                for item_key, item_value in frequency_features.items()
                if item_key != "spectrum"
            },
            "quality": quality,
            "advanced_analysis": advanced_random_process_analysis(
                signal,
                state.bundle.config.sample_rate,
                self._advanced_config(state),
            ),
        }
        summary_payload["insights"] = self._insights_from_summary({
            "time_features": time_features,
            "frequency_features": frequency_features,
            "quality": quality,
        })
        return {
            "key": key,
            "label": label,
            "frequency": freq,
            "power": power,
            "summary": summary_payload,
        }

    def _number_after(self, text: str, keys: list[str], default: float | None) -> float | None:
        import re

        for key in keys:
            pattern = rf"{re.escape(key)}\s*[:=：]?\s*(\d+(?:\.\d+)?)"
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return float(match.group(1))
        return default

    def _extract_duration(self, text: str, default: float) -> float:
        import re

        for pattern in [
            r"(?:时长|duration)\s*[:=：]?\s*(\d+(?:\.\d+)?)",
            r"(\d+(?:\.\d+)?)\s*秒",
            r"(\d+(?:\.\d+)?)\s*s\b",
        ]:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return float(match.group(1))
        return default

    def _has_explicit_duration(self, text: str) -> bool:
        import re

        return any(
            re.search(pattern, text, flags=re.IGNORECASE)
            for pattern in [
                r"(?:时长|duration)\s*[:=：]?\s*\d+(?:\.\d+)?",
                r"\d+(?:\.\d+)?\s*秒",
                r"\d+(?:\.\d+)?\s*s\b",
            ]
        )

    def _extract_sample_rate(self, text: str, default: float) -> float:
        import re

        for pattern in [
            r"(?:采样率|sample[_ -]?rate)\s*[:=：]?\s*(\d+(?:\.\d+)?)",
            r"(\d+(?:\.\d+)?)\s*(?:hz|赫兹)\s*(?:采样|采样率)",
        ]:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return float(match.group(1))

        hz_values = [
            float(value)
            for value in re.findall(r"(\d+(?:\.\d+)?)\s*(?:hz|赫兹)", text, flags=re.IGNORECASE)
        ]
        if len(hz_values) >= 2:
            return hz_values[0]
        if len(hz_values) == 1 and "主频" not in text and "频率" not in text:
            return hz_values[0]
        return default

    def _has_explicit_sample_rate(self, text: str) -> bool:
        import re

        return any(
            re.search(pattern, text, flags=re.IGNORECASE)
            for pattern in [
                r"(?:采样率|sample[_ -]?rate)\s*[:=：]?\s*\d+(?:\.\d+)?",
                r"\d+(?:\.\d+)?\s*(?:hz|赫兹)\s*(?:采样|采样率)",
            ]
        )

    def _waveform_from_text(self, text: str, model_hint: str = "") -> str:
        lowered = f"{model_hint} {text}".lower()
        if any(word in lowered for word in ["方波", "square"]):
            return "square"
        if any(word in lowered for word in ["三角波", "triangle"]):
            return "triangle"
        if any(word in lowered for word in ["锯齿波", "sawtooth", "saw"]):
            return "sawtooth"
        if any(word in lowered for word in ["多频", "多正弦", "multi_sine", "multi-sine"]):
            return "multi_sine"
        if any(word in lowered for word in ["线性调频", "扫频", "chirp", "lfm"]):
            return "chirp"
        if any(word in lowered for word in ["正弦", "sin", "sine", "sine_gaussian"]):
            return "sine"
        return "random_process"

    def _noise_model_from_text(self, text: str, model_hint: str = "") -> str:
        lowered = f"{model_hint} {text}".lower()
        wants_gaussian = any(word in lowered for word in ["高斯", "gaussian", "白噪声", "white noise", "sine_gaussian"])
        wants_impulse = any(word in lowered for word in ["脉冲", "冲击", "impulse", "突发"])
        if wants_gaussian and wants_impulse:
            return "gaussian_impulse"
        if wants_gaussian:
            return "gaussian"
        if any(word in lowered for word in ["均匀", "uniform"]):
            return "uniform"
        if wants_impulse:
            return "impulse"
        if any(word in lowered for word in ["ar", "相关噪声", "有色噪声", "colored", "色噪声"]):
            return "ar"
        return "mixed"

    def _waveform_label(self, waveform: str) -> str:
        return {
            "sine": "正弦信号",
            "square": "方波信号",
            "triangle": "三角波信号",
            "sawtooth": "锯齿波信号",
            "multi_sine": "多频正弦信号",
            "chirp": "线性调频信号",
            "random_process": "随机过程仿真信号",
        }.get(waveform, waveform)

    def _noise_model_label(self, noise_model: str) -> str:
        return {
            "gaussian": "高斯白噪声",
            "uniform": "均匀噪声",
            "impulse": "脉冲干扰",
            "ar": "AR相关噪声",
            "gaussian_impulse": "高斯白噪声 + 脉冲干扰",
            "mixed": "混合随机噪声",
        }.get(noise_model, noise_model)

    def _extract_frequency(self, text: str, default: float) -> float:
        import re

        for pattern in [
            r"(?:主频|目标频率|base[_ -]?frequency)\s*[:=：]?\s*(\d+(?:\.\d+)?)",
            r"(?:频率|frequency)\s*[:=：]?\s*(\d+(?:\.\d+)?)",
        ]:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return float(match.group(1))

        hz_values = [
            float(value)
            for value in re.findall(r"(\d+(?:\.\d+)?)\s*(?:hz|赫兹)", text, flags=re.IGNORECASE)
        ]
        if len(hz_values) >= 2:
            return hz_values[-1]
        if len(hz_values) == 1 and ("主频" in text or "频率" in text):
            return hz_values[0]
        return default

    def _extract_seed(self, text: str) -> int:
        import re

        for pattern in [
            r"(?:seed|随机种子|种子)\s*[:=：]?\s*(\d+)",
        ]:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return int(match.group(1)) % (2**32)
        return secrets.randbits(32)
