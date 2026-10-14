import { describe, expect, it } from "vitest";
import { auditText, tokenExpiryText, tokenScopeText } from "./auth";

const token = { id: 1, name: "t", created_at: "", last_used_at: null };

describe("token and audit wording", () => {
  it("says what a token may do and when it ends", () => {
    expect(tokenScopeText({ ...token, scope: "read" })).toMatch(/Read-only/);
    expect(tokenScopeText(token)).toBe("Full access");
    expect(tokenExpiryText(token)).toBe("Never expires");
    expect(tokenExpiryText({ ...token, expires_at: "2030-01-02T00:00:00" })).toMatch(/^Expires /);
    expect(tokenExpiryText({ ...token, expires_at: "2020-01-02T00:00:00", expired: true })).toMatch(/^Expired on .* — delete it$/);
  });
  it("turns audit rows into sentences", () => {
    const row = (kind: string, username: string | null = "admin", detail = "") => ({ id: 1, at: "", kind, username, ip: null, detail });
    expect(auditText(row("login_ok"))).toBe("“admin” signed in");
    expect(auditText(row("login_failed", "ghost"))).toBe("Failed sign-in attempt for “ghost”");
    expect(auditText(row("login_failed", null))).toBe("Failed sign-in attempt for someone");
    expect(auditText(row("token_created", "admin", "ha (read, expires in 90 days)"))).toBe("Access token created: ha (read, expires in 90 days)");
    expect(auditText(row("login_toggled", "admin", "login turned off"))).toBe("Login turned off");
    expect(auditText(row("setup"))).toMatch(/Administrator account created/);
  });
});
