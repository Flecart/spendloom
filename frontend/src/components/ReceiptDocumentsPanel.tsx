import { useEffect, useState } from "react";
import {
  Box,
  Button,
  Stack,
  Typography,
} from "@mui/material";
import { OpenInNewRounded } from "@mui/icons-material";

import { ReceiptDocument } from "../api";

interface ReceiptDocumentsPanelProps {
  documents: ReceiptDocument[];
}

export default function ReceiptDocumentsPanel({
  documents,
}: ReceiptDocumentsPanelProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);

  useEffect(() => {
    setSelectedIndex(0);
  }, [documents]);

  if (documents.length === 0) {
    return <Box className="empty-state">No receipt documents</Box>;
  }

  const selected = documents[Math.min(selectedIndex, documents.length - 1)];
  const previewUrl = selected.preview_url
    || (selected.mime_type.startsWith("image/") ? selected.file_url : null);

  return (
    <Stack spacing={1.5}>
      <Typography variant="subtitle2">
        {documents.length} receipt document{documents.length === 1 ? "" : "s"}
      </Typography>
      {previewUrl ? (
        <img
          className="receipt-preview"
          src={previewUrl}
          alt={`Receipt document ${selectedIndex + 1}`}
        />
      ) : (
        <Box className="empty-state">Preview unavailable</Box>
      )}
      <Stack spacing={1}>
        {documents.map((document, index) => (
          <Button
            key={document.receipt_id}
            variant={index === selectedIndex ? "contained" : "outlined"}
            onClick={() => setSelectedIndex(index)}
            sx={{ justifyContent: "space-between" }}
          >
            <span>{index + 1}. {document.filename}</span>
            <span>{(document.size_bytes / 1024 / 1024).toFixed(1)} MB</span>
          </Button>
        ))}
      </Stack>
      <Button
        href={selected.file_url}
        target="_blank"
        rel="noreferrer"
        startIcon={<OpenInNewRounded />}
      >
        Open selected original
      </Button>
    </Stack>
  );
}
