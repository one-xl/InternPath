import type { ResumeFileStatus } from "../../types/resume";
import { Badge } from "../ui/Badge";

const statusText: Record<ResumeFileStatus, string> = {
  idle: "等待上传简历",
  selected: "已选择文件",
  uploading: "正在上传文件",
  uploaded: "文件已上传",
  parsing: "正在解析简历内容",
  parsed: "简历解析完成",
  indexing: "正在构建简历检索索引",
  indexed: "简历解析完成",
  failed: "简历解析失败，请重新上传",
};

export function ResumeParseStatus({ status }: { status: ResumeFileStatus }) {
  const tone = status === "failed" ? "danger" : status === "indexed" || status === "parsed" ? "success" : status === "idle" ? "neutral" : "info";
  return <Badge tone={tone}>{statusText[status]}</Badge>;
}
