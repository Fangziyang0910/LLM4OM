// 澄清问答:确认原声明或提交修订;提交前可预览将要提交的问题修订。
import { useState } from "react";
import { pretty } from "../ui";

interface Question {
  question_id: string;
  kind: string;
  question: string;
  statement?: string | null;
  statement_ref?: { kind: string; id: string } | null;
}

export interface ClarificationPayload {
  answers?: unknown;
  revised_problem?: any;
}

export function buildClarificationSubmission(
  request: { request_id: string; questions: Question[] },
  problem: any,
  fields: { question: Question; text: string; choice: string }[],
): ClarificationPayload {
  const answers = fields.map(({ question, text, choice }) => {
    if (question.kind === "confirm_existing" && !choice) throw new Error("请回答所有澄清问题。");
    const value = choice === "confirm" ? true : text.trim();
    if (value !== true && (!value || value.length > 4096))
      throw new Error("请填写完整的补充或修订信息，最多4096个字符。");
    return { question_id: question.question_id, value };
  });
  const revise = answers.some((answer) => answer.value !== true);
  const response = {
    schema_version: "0.1.0",
    request_id: request.request_id,
    action: revise ? "revise" : "confirm",
    answers,
  };
  if (!revise) return { answers: response };
  const revised = structuredClone(problem);
  revised.revision = problem.revision + ".clarification-" + request.request_id.slice(0, 8);
  const changes: string[] = [];
  fields.forEach(({ question }, index) => {
    const answer = answers[index];
    if (answer.value === true) return;
    if (question.kind === "confirm_existing") {
      const source = revised[
        question.statement_ref?.kind === "requirement" ? "requirements" : "assumptions"
      ].find((item: any) => item.id === question.statement_ref?.id);
      if (!source) throw new Error("原声明不在当前公开问题中，无法提交修订。");
      source.text = answer.value;
      if (question.statement_ref?.kind === "assumption") {
        source.status = "confirmed";
        source.origin = "user_clarification";
      }
      if ("source_span" in source) source.source_span = null;
      changes.push("修订原声明（" + question.statement + "）：" + answer.value);
    } else {
      revised.requirements.push({
        id: "CLARIFY-" + request.request_id.slice(0, 8) + "-" + (index + 1),
        text: answer.value,
        category: "other",
        source_span: null,
      });
      changes.push(question.question + "\n" + answer.value);
    }
  });
  revised.description +=
    "\n\n本次问题修订（以下规则替代有冲突的原声明）：\n" + changes.join("\n");
  return { answers: response, revised_problem: revised };
}

export function Clarification({
  request,
  problem,
  rawRequest,
  onSubmit,
  onError,
}: {
  request: { request_id: string; questions: Question[] };
  problem: any;
  rawRequest: string;
  onSubmit: (payload: ClarificationPayload) => void;
  onError: (message: string) => void;
}) {
  const [fields, setFields] = useState(() =>
    request.questions.map((question) => ({ question, text: "", choice: "" })),
  );
  const preview = (() => {
    try {
      return buildClarificationSubmission(request, problem, fields);
    } catch {
      return null;
    }
  })();
  const revised = preview?.revised_problem;
  const update = (index: number, patch: Partial<{ text: string; choice: string }>) =>
    setFields((prior) => prior.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  return (
    <div id="clarification" className="panel" data-request-id={request.request_id}>
      <h2>需要你补充一点信息</h2>
      <p className="hint">确认已有声明可继续当前运行。补充或修改规则会创建问题的新版本，原记录会保留。</p>
      <div id="clarification-questions">
        {fields.map(({ question, text, choice }, index) => (
          <fieldset className="clarification-question" key={question.question_id}>
            <legend>{question.question}</legend>
            {question.kind === "confirm_existing" ? (
              <p className="existing-statement">原声明：{question.statement}</p>
            ) : null}
            {question.kind === "confirm_existing" ? (
              <select
                aria-label={question.question}
                value={choice}
                onChange={(event) => update(index, { choice: event.target.value })}
              >
                <option value="">请选择</option>
                <option value="confirm">确认原声明</option>
                <option value="replace">修改这项声明</option>
              </select>
            ) : null}
            <label
              htmlFor={"clarification-answer-" + index}
              hidden={question.kind === "confirm_existing" && choice !== "replace"}
            >
              {question.kind === "confirm_existing" ? "修改后的完整声明" : "你的补充信息"}
            </label>
            <textarea
              id={"clarification-answer-" + index}
              rows={3}
              maxLength={4096}
              placeholder="请直接描述规则、数值和单位。"
              value={text}
              hidden={question.kind === "confirm_existing" && choice !== "replace"}
              onChange={(event) => update(index, { text: event.target.value })}
            />
          </fieldset>
        ))}
      </div>
      <details id="clarification-preview" hidden={!revised}>
        <summary>查看将要提交的问题修订</summary>
        <pre id="clarification-description">{pretty(revised?.description) || ""}</pre>
      </details>
      <button
        id="answer-submit"
        className="primary"
        onClick={() => {
          try {
            onSubmit(buildClarificationSubmission(request, problem, fields));
          } catch (error) {
            onError((error as Error).message);
          }
        }}
      >
        {revised ? "确认修订并继续" : "提交回答并继续"}
      </button>
      <details className="raw-record">
        <summary>查看原始澄清请求</summary>
        <pre id="clarification-request">{rawRequest}</pre>
      </details>
    </div>
  );
}
