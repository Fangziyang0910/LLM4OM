// 配置体检(doctor)结果呈现:分层显示通过项/失败项与目录检查详情。
export function Connectivity({ report }: { report: any }) {
  const labels: Record<string, string> = {
    reachable: "接口可达",
    failed: "检查未通过",
    not_supported: "不支持目录检查",
    not_checked: "未执行",
    not_applicable: "无需网络检查",
  };
  const result = report.connectivity_checks;
  const checks = (result.checks || []).filter((item: any) => item.status !== "not_checked");
  const passed = checks.filter((item: any) => item.status === "reachable").length;
  const failed = checks.filter((item: any) => item.status === "failed").length;
  return (
    <>
      <strong>配置与兼容性检查通过</strong>
      {result.status !== "not_requested" && checks.length ? (
        <p className="doctor-summary">
          接口检查:通过 {passed} 项 · 未通过 {failed} 项
          {failed ? ";建议检查服务地址与凭据后重试。" : ";可以提交运行。"}
        </p>
      ) : null}
      {result.status === "not_requested" ? (
        <p className="hint">未请求网络检查。勾选上方选项后可读取模型目录。</p>
      ) : (
        (result.checks || []).map((item: any, index: number) => (
          <div className="connectivity-row" key={index}>
            <span>
              {(item.role === "default" ? "默认模型" : item.role) + " · " + (item.model || "")}
            </span>
            <strong>{labels[item.status] || item.status}</strong>
            {item.model_listed != null ? (
              <small>{item.model_listed ? "该页目录包含此模型" : "该页目录未列出此模型"}</small>
            ) : null}
            {item.http_status ? <small>HTTP {item.http_status}</small> : null}
          </div>
        ))
      )}
      <p className="hint">
        只读取目录，不发起文本生成。目录可能分页或使用别名；生成能力以实际运行结果为准。
      </p>
    </>
  );
}
