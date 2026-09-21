export function planText(source: string) {
  const match = source.match(/```scholarmate-plan\s*\n([\s\S]*?)\n```/);
  if (match) {
    try {
      const parsed = JSON.parse(match[1]);
      if (typeof parsed.plan_content === "string") return parsed.plan_content;
    } catch {
      /* Keep the original text if malformed. */
    }
  }
  return source;
}

