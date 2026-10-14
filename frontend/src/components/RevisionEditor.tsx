import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { pretty } from "../ui";
import { RevisionFields, buildDoc, validateRevision } from "./Revision";
import type { EditDocument, Notice, Snapshot } from "../types";

export function RevisionEditor({ snapshot, notice, onClose, onSubmitted, apiKey }: {
  snapshot: Snapshot; notice: Notice; onClose: () => void; onSubmitted: () => Promise<void>;
  apiKey?: string;
}) {
  const currentJob = snapshot.job.job_id;
  const current = useRef(snapshot);
  current.current = snapshot;
  const requestSequence = useRef(0);
  const [editOperation, setEditOperation] = useState<EditDocument["operation"]>("code");
  const [editTemplate, setEditTemplate] = useState<EditDocument | null>(null);
  const [editBase, setEditBase] = useState<EditDocument | null>(null);
  const [editOverrides, setEditOverrides] = useState<Record<string, string>>({});
  const [editDocumentText, setEditDocumentText] = useState("");
  const [editBusy, setEditBusy] = useState(true);
  const editParent = useRef<{ job: string; run: string } | null>(null);
  const loadEditTemplate = async (operation: EditDocument["operation"] = editOperation) => {
    const parent = { job: currentJob, run: snapshot.job.run_id! };
    const sequence = ++requestSequence.current;
    setEditBusy(true);
    try {
      const document = await api<EditDocument>(
        `/api/jobs/${parent.job}/edit-template?operation=${operation}&run_id=${parent.run}`,
      );
      if (sequence !== requestSequence.current || current.current.job.job_id !== parent.job || current.current.job.run_id !== parent.run) return;
      setEditDocumentText(pretty(document));
      editParent.current = parent;
      Object.assign(window, { editParent: parent });
      setEditTemplate(document);
      setEditBase(structuredClone(document));
      setEditOverrides({});
    } catch (error) {
      if (sequence === requestSequence.current) throw error;
    } finally {
      if (sequence === requestSequence.current) setEditBusy(false);
    }
  };

  const submitEdit = async () => {
    const sequence = requestSequence.current;
    try {
      setEditBusy(true);
      if (!editTemplate || currentJob !== editParent.current?.job)
        throw new Error("请先载入当前运行的编辑内容。");
      const edits = buildDoc(editBase!, editOverrides, editTemplate!);
      const problem = await validateEdit(edits);
      if (sequence !== requestSequence.current) return;
      setEditDocumentText(pretty(edits));
      await api(`/api/jobs/${currentJob}/edit`, {
        edits: problem,
        parent_run_id: editParent.current!.run,
      }, apiKey || undefined);
      if (sequence !== requestSequence.current) return;
      onClose();
      notice("人工修订已提交。原运行保留，新结果会记录父运行和预算。");
      await onSubmitted();
    } catch (error) {
      if (sequence === requestSequence.current) notice((error as Error).message, true);
    } finally {
      if (sequence === requestSequence.current) setEditBusy(false);
    }
  };

  const validateEdit = async (edits: EditDocument) => {
    const message = validateRevision(edits, editTemplate!, snapshot.contents["budget-ledger.json"]);
    if (message) throw new Error(message);
    const latest = await api<Snapshot>(`/api/jobs/${currentJob}?run_id=${editParent.current!.run}`);
    if (latest.job.run_id !== editParent.current!.run || current.current.job.run_id !== editParent.current!.run)
      throw new Error("运行版本已改变，请重新载入编辑内容。");
    return edits;
  };

  const editDoc = useMemo(
    () => (editBase ? buildDoc(editBase!, editOverrides, editTemplate!) : null),
    [editBase, editOverrides, editTemplate],
  );
  useEffect(() => {
    if (editDoc) setEditDocumentText(pretty(editDoc));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editDoc]);

  const structuralMutation = (mutate: (doc: EditDocument) => void) => {
    const next = buildDoc(editBase!, editOverrides, editTemplate!);
    mutate(next);
    setEditBase(next);
    setEditOverrides({});
  };

  useEffect(() => {
    loadEditTemplate(editOperation).catch(error => notice(error.message, true));
    document.getElementById("assisted-editor")?.scrollIntoView({ behavior: "smooth", block: "start" });
    return () => { requestSequence.current++; };
  }, [editOperation]);
  return (
    <section id="assisted-editor" className="panel">
      <h3>编辑并创建新版本</h3>
      <label htmlFor="edit-operation">编辑范围</label>
      <select
        id="edit-operation"
        value={editOperation}
        disabled={editBusy}
        onChange={(event) => {
          setEditOperation(event.target.value as EditDocument["operation"]);
        }}
      >
        <option value="code">修改求解代码</option>
        <option value="problem">修改问题描述与规则</option>
        <option value="formulation">修改数学模型</option>
      </select>
      <button
        id="load-edit-template"
        className="secondary"
        disabled={editBusy}
        onClick={() => loadEditTemplate().catch((error) => notice(error.message, true))}
      >
        重新载入原内容
      </button>
      <p className="hint">
        原版本会保留。代码修订复用原数学表述；问题修订会重新建模。新结果标记为人工辅助。
      </p>
      {editBase ? (
        <RevisionFields
          base={editBase}
          overrides={editOverrides}
          onInput={(key, value) => setEditOverrides((prior) => ({ ...prior, [key]: value }))}
          onRemoveConstraint={(index) =>
            structuralMutation((doc) => doc.structured_ir!.constraints.splice(index, 1))
          }
          onAddConstraint={() =>
            structuralMutation((doc) => {
              let counter = 1;
              while (doc.structured_ir!.constraints.some((item) => item.id === "C_USER_" + counter))
                counter++;
              doc.structured_ir!.constraints.push({
                id: "C_USER_" + counter,
                expression: {
                  constant: 0,
                  terms: doc.structured_ir!.variables.map((item) => ({
                    variable_id: item.id,
                    coefficient: 0,
                  })),
                },
                sense: "le",
                rhs: 0,
                requirement_ids: [],
              });
            })
          }
          ledger={snapshot.contents["budget-ledger.json"]}
        />
      ) : (
        <div id="revision-fields" />
      )}
      <details
        id="revision-advanced"
        className="raw-record"
        ref={(el) => {
          if (el && editTemplate)
            el.open = editTemplate.operation === "formulation" && !editTemplate.structured_ir;
        }}
      >
        <summary>高级：完整编辑文档</summary>
        <textarea
          id="assisted-document"
          rows={16}
          aria-label="完整编辑文档 JSON"
          value={editDocumentText}
          onChange={(event) => setEditDocumentText(event.target.value)}
        />
        <button
          id="apply-edit-document"
          className="secondary"
          onClick={() => {
            try {
              const document: EditDocument = JSON.parse(editDocumentText);
              if (document.operation !== editOperation)
                throw new Error("完整文档的编辑范围应与当前选择一致。");
              validateRevision(document, editTemplate!, snapshot.contents["budget-ledger.json"]);
              buildDoc(document, {}, editTemplate!);
              setEditBase(document);
              setEditOverrides({});
              notice("完整编辑文档已应用到表单。");
            } catch (error) {
              notice((error as Error).message, true);
            }
          }}
        >
          应用完整编辑文档
        </button>
      </details>
      <div className="actions">
        <button id="submit-edit" className="primary" disabled={editBusy} onClick={submitEdit}>
          确认修订并运行
        </button>
        <button id="close-edit" className="secondary" onClick={onClose}>
          取消编辑
        </button>
      </div>
    </section>
  );
}
