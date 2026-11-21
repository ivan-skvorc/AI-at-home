import { isRecord } from "@/lib/utils";

export async function readSkillErrorDetail(
  response: Response,
): Promise<unknown> {
  const data: unknown = await response.json().catch(() => null);
  return isRecord(data) ? data.detail : undefined;
}
