// MetricTable.tsx - 指标表。
import { automation } from "../../lib/api";

export function MetricTable({ metrics }: { metrics: automation.Metric[] }) {
  if (!metrics || metrics.length === 0) {
    return <div className="text-sm text-muted-foreground">暂无指标</div>;
  }
  return (
    <table className="w-full text-sm">
      <thead className="text-xs text-muted-foreground">
        <tr>
          <th className="text-left py-1">caseId</th>
          <th className="text-left py-1">name</th>
          <th className="text-left py-1">value</th>
          <th className="text-left py-1">unit</th>
        </tr>
      </thead>
      <tbody>
        {metrics.map((m, i) => (
          <tr key={i} className="border-t">
            <td className="py-1 font-mono">{m.caseId}</td>
            <td className="py-1">{m.name}</td>
            <td className="py-1">{m.value ?? m.textValue ?? ""}</td>
            <td className="py-1">{m.unit}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}