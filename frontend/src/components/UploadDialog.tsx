import {
  ChangeEvent,
  DragEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  InputLabel,
  LinearProgress,
  MenuItem,
  Select,
  TextField,
  Typography,
} from "@mui/material";
import {
  CloudUploadRounded,
  InsertDriveFileRounded,
} from "@mui/icons-material";

import {
  api,
  RecurringOccurrence,
} from "../api";

interface UploadDialogProps {
  open: boolean;
  onClose: () => void;
  onUploaded: () => void;
}

export default function UploadDialog({
  open,
  onClose,
  onUploaded,
}: UploadDialogProps) {
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [caption, setCaption] = useState("");
  const [groupFiles, setGroupFiles] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [occurrences, setOccurrences] = useState<RecurringOccurrence[]>([]);
  const [occurrenceId, setOccurrenceId] = useState("");

  useEffect(() => {
    if (!open) {
      return;
    }
    api<RecurringOccurrence[]>("/api/recurring-occurrences")
      .then((items) => {
        setOccurrences(items.filter((item) => item.entry_type === "expense"));
      })
      .catch(() => {
        setOccurrences([]);
      });
  }, [open]);

  const selectFiles = (list: FileList | null) => {
    const selected = list ? Array.from(list) : [];
    setFiles(selected);
    if (occurrenceId && selected.length > 1) {
      setGroupFiles(true);
    } else if (selected.length < 2) {
      setGroupFiles(false);
    }
  };

  const handleDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    selectFiles(event.dataTransfer.files);
  };

  const upload = async () => {
    setLoading(true);
    setError("");
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    body.append("group_files", String(groupFiles));
    if (caption) {
      body.append("caption", caption);
    }
    if (occurrenceId) {
      body.append("recurring_occurrence_id", occurrenceId);
    }
    try {
      await api("/api/ingestions", {
        method: "POST",
        body,
      });
      setFiles([]);
      setCaption("");
      setGroupFiles(false);
      setOccurrenceId("");
      onUploaded();
    } catch (uploadError) {
      setError(
        uploadError instanceof Error
          ? uploadError.message
          : "Upload failed",
      );
    } finally {
      setLoading(false);
    }
  };

  const queuedReceiptCount = groupFiles ? 1 : files.length;

  return (
    <Dialog
      open={open}
      onClose={loading ? undefined : onClose}
      fullWidth
      maxWidth="sm"
    >
      <DialogTitle>Add receipts</DialogTitle>
      <DialogContent sx={{ display: "grid", gap: 2.5 }}>
        {loading && <LinearProgress />}
        {error && <Alert severity="error">{error}</Alert>}
        <Box
          className={`drop-zone ${dragging ? "dragging" : ""}`}
          onClick={() => input.current?.click()}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
        >
          <input
            ref={input}
            hidden
            multiple
            type="file"
            accept="image/jpeg,image/png,image/webp,image/heic,image/heif,application/pdf"
            onChange={(event: ChangeEvent<HTMLInputElement>) => selectFiles(event.target.files)}
          />
          <CloudUploadRounded color="primary" sx={{ fontSize: 52 }} />
          <Typography fontWeight={750} sx={{ mt: 1 }}>
            Drop receipts here
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Images, HEIC, or PDF · up to 50 MB each
          </Typography>
        </Box>
        {files.length > 0 && (
          <Box sx={{ display: "grid", gap: 1 }}>
            {files.map((file) => (
              <Box
                key={`${file.name}-${file.size}`}
                sx={{
                  display: "flex",
                  gap: 1,
                  alignItems: "center",
                  p: 1.5,
                  borderRadius: 3,
                  bgcolor: "action.hover",
                }}
              >
                <InsertDriveFileRounded color="action" />
                <Box sx={{ minWidth: 0 }}>
                  <Typography noWrap fontWeight={650}>{file.name}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    {(file.size / 1024 / 1024).toFixed(1)} MB
                  </Typography>
                </Box>
              </Box>
            ))}
          </Box>
        )}
        {files.length > 1 && (
          <FormControlLabel
            control={(
              <Checkbox
                checked={groupFiles}
                disabled={Boolean(occurrenceId)}
                onChange={(event) => setGroupFiles(event.target.checked)}
              />
            )}
            label={
              occurrenceId
                ? "Files are grouped for the selected recurring expense"
                : "These files belong to one receipt"
            }
          />
        )}
        <TextField
          label="Context or memo (optional)"
          multiline
          minRows={2}
          value={caption}
          onChange={(event) => setCaption(event.target.value)}
          helperText="This helps classification and is stored with the receipt."
        />
        <FormControl fullWidth>
          <InputLabel id="recurring-occurrence-label">
            Recurring expense (optional)
          </InputLabel>
          <Select
            labelId="recurring-occurrence-label"
            label="Recurring expense (optional)"
            value={occurrenceId}
            onChange={(event) => {
              setOccurrenceId(event.target.value);
              if (event.target.value && files.length > 1) {
                setGroupFiles(true);
              }
            }}
          >
            <MenuItem value="">None</MenuItem>
            {occurrences.map((occurrence) => (
              <MenuItem key={occurrence.id} value={occurrence.id}>
                {occurrence.recurring_item_name} · {occurrence.due_date}
                {occurrence.expected_amount
                  ? ` · ${occurrence.expected_amount} ${occurrence.currency}`
                  : ""}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </DialogContent>
      <DialogActions sx={{ p: 2.5 }}>
        <Button onClick={onClose} disabled={loading}>Cancel</Button>
        <Button
          variant="contained"
          onClick={upload}
          disabled={!files.length || loading}
        >
          Queue {queuedReceiptCount || ""} receipt{queuedReceiptCount === 1 ? "" : "s"}
          {groupFiles ? ` (${files.length} documents)` : ""}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
