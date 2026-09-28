// Input protocol (spec §3): «стоп» is handled here and never sent to the agent; while a run
// is active everything else is refused; mentions are board keys picked by clicking objects.

const STOP = /^(стоп|останови(сь)?|прекрати|stop)\s*[.!]?$/i;

export const isStop = (text: string) => STOP.test(text.trim());

export type Decision = "send" | "stop" | "busy" | "ignore";

export function decide(text: string, running: boolean): Decision {
  if (!text.trim()) return "ignore";
  if (isStop(text)) return running ? "stop" : "ignore";
  return running ? "busy" : "send";
}

export function toggleMention(mentions: string[], key: string): string[] {
  return mentions.includes(key) ? mentions.filter((k) => k !== key) : [...mentions, key];
}
