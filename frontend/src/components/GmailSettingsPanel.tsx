import { FormEvent, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { AddRounded, RefreshRounded } from "@mui/icons-material";

import {
  api,
  Category,
  GmailStatus,
  RecurringItem,
  Scope,
} from "../api";

interface SenderForm {
  sender_address: string;
  recurring_item_id: string;
  category_id: string;
  scope: "" | Scope;
  match_window_days: string;
}

const initialSender: SenderForm = {
  sender_address: "",
  recurring_item_id: "",
  category_id: "",
  scope: "",
  match_window_days: "45",
};

export default function GmailSettingsPanel() {
  const [status, setStatus] = useState<GmailStatus | null>(null);
  const [recurring, setRecurring] = useState<RecurringItem[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [form, setForm] = useState<SenderForm>(initialSender);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = (): Promise<void> => Promise.all([
    api<GmailStatus>("/api/integrations/gmail"),
    api<RecurringItem[]>("/api/recurring-items"),
    api<Category[]>("/api/categories"),
  ])
    .then(([gmail, loadedRecurring, loadedCategories]) => {
      setStatus(gmail);
      setRecurring(loadedRecurring);
      setCategories(loadedCategories);
    })
    .catch((loadError: Error) => setError(loadError.message));

  useEffect(() => {
    load();
  }, []);

  const addSender = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    try {
      await api("/api/integrations/gmail/sender-rules", {
        method: "POST",
        body: JSON.stringify({
          sender_address: form.sender_address,
          recurring_item_id: form.recurring_item_id || null,
          category_id: form.category_id || null,
          scope: form.scope || null,
          match_window_days: Number(form.match_window_days),
        }),
      });
      setForm(initialSender);
      setNotice("Sender added");
      await load();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Could not add sender");
    }
  };

  const sync = async (): Promise<void> => {
    try {
      const result = await api<{ imported: number }>("/api/integrations/gmail/sync", {
        method: "POST",
      });
      setNotice(`Gmail sync completed; ${result.imported} message(s) imported.`);
      await load();
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : "Gmail sync failed");
    }
  };

  const removeSender = async (ruleId: string): Promise<void> => {
    try {
      await api(`/api/integrations/gmail/sender-rules/${ruleId}`, { method: "DELETE" });
      await load();
    } catch (removeError) {
      setError(removeError instanceof Error ? removeError.message : "Could not remove sender");
    }
  };

  const disconnect = async (): Promise<void> => {
    if (!window.confirm("Disconnect Gmail and revoke Spendloom's token?")) {
      return;
    }
    try {
      await api("/api/integrations/gmail/disconnect", { method: "POST" });
      setNotice("Gmail disconnected");
      await load();
    } catch (disconnectError) {
      setError(disconnectError instanceof Error ? disconnectError.message : "Could not disconnect Gmail");
    }
  };

  if (!status) {
    return error ? <Alert severity="error">{error}</Alert> : <Typography>Loading Gmail…</Typography>;
  }

  return (
    <Card>
      <CardContent>
        <Stack spacing={2.5}>
          <Box>
            <Typography variant="h6" fontWeight={750}>Gmail receipt inbox</Typography>
            <Typography color="text.secondary">
              Spendloom only fetches messages whose exact sender address you allow below.
              Google&apos;s read-only OAuth permission technically grants mailbox-wide read access.
            </Typography>
          </Box>
          {error && <Alert severity="error" onClose={() => setError("")}>{error}</Alert>}
          {notice && <Alert severity="success" onClose={() => setNotice("")}>{notice}</Alert>}
          {!status.configured && (
            <Alert severity="warning">
              Set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, and GMAIL_TOKEN_ENCRYPTION_KEY on the server first.
            </Alert>
          )}
          {status.configured && !status.connected && (
            <Button
              variant="contained"
              href="/api/integrations/gmail/oauth/start"
              sx={{ alignSelf: "start" }}
            >
              Connect Gmail
            </Button>
          )}
          {status.connected && (
            <>
              <Box sx={{ display: "flex", gap: 1, alignItems: "center", flexWrap: "wrap" }}>
                <Chip color="success" label={`Connected: ${status.email_address}`} />
                <Button startIcon={<RefreshRounded />} onClick={sync}>Sync now</Button>
                <Button color="error" onClick={disconnect}>Disconnect</Button>
              </Box>
              <Typography variant="body2" color="text.secondary">
                Last sync: {status.last_synced_at
                  ? new Date(status.last_synced_at).toLocaleString()
                  : "not yet"}
              </Typography>
              {status.error_message && <Alert severity="error">{status.error_message}</Alert>}
              <Box
                component="form"
                onSubmit={addSender}
                sx={{
                  display: "grid",
                  gridTemplateColumns: { xs: "1fr", md: "2fr 2fr 2fr 1fr auto" },
                  gap: 1,
                }}
              >
                <TextField
                  required
                  size="small"
                  type="email"
                  label="Exact sender"
                  placeholder="noreply@iliad.it"
                  value={form.sender_address}
                  onChange={(event) => setForm({ ...form, sender_address: event.target.value })}
                />
                <TextField
                  select
                  size="small"
                  label="Recurring item"
                  value={form.recurring_item_id}
                  onChange={(event) => setForm({ ...form, recurring_item_id: event.target.value })}
                >
                  <MenuItem value="">No automatic match</MenuItem>
                  {recurring.filter((item) => item.entry_type === "expense").map((item) => (
                    <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>
                  ))}
                </TextField>
                <TextField
                  select
                  size="small"
                  label="Default category"
                  value={form.category_id}
                  onChange={(event) => setForm({ ...form, category_id: event.target.value })}
                >
                  <MenuItem value="">Use extraction</MenuItem>
                  {categories.map((category) => (
                    <MenuItem key={category.id} value={category.id}>{category.name}</MenuItem>
                  ))}
                </TextField>
                <TextField
                  select
                  size="small"
                  label="Scope"
                  value={form.scope}
                  onChange={(event) => setForm({ ...form, scope: event.target.value as "" | Scope })}
                >
                  <MenuItem value="">Use extraction</MenuItem>
                  <MenuItem value="personal">Personal</MenuItem>
                  <MenuItem value="business">Business</MenuItem>
                  <MenuItem value="unknown">Unknown</MenuItem>
                </TextField>
                <Button type="submit" variant="outlined" startIcon={<AddRounded />}>Add</Button>
              </Box>
              <Stack spacing={1}>
                {status.sender_rules.map((rule) => (
                  <Box
                    key={rule.id}
                    sx={{ display: "flex", gap: 1, alignItems: "center", flexWrap: "wrap" }}
                  >
                    <Typography sx={{ flex: 1 }} fontWeight={650}>{rule.sender_address}</Typography>
                    {rule.recurring_item_name && <Chip size="small" label={rule.recurring_item_name} />}
                    {!rule.enabled && <Chip size="small" color="warning" label="Disabled" />}
                    <Button size="small" color="error" onClick={() => removeSender(rule.id)}>
                      Remove
                    </Button>
                  </Box>
                ))}
              </Stack>
            </>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
