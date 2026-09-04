import { ChangeEvent, useState } from "react";
import { Button } from "@mui/material";
import { AttachFileRounded } from "@mui/icons-material";

import { api, SupportingDocument } from "../api";

interface DocumentUploadProps {
  targetType: "expense" | "income" | "contract" | "invoice" | "occurrence";
  targetId: string;
  onUploaded: (document: SupportingDocument) => void;
  onError: (message: string) => void;
}

export default function DocumentUpload({
  targetType,
  targetId,
  onUploaded,
  onError,
}: DocumentUploadProps) {
  const [uploading, setUploading] = useState(false);

  const upload = async (event: ChangeEvent<HTMLInputElement>): Promise<void> => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("target_type", targetType);
    form.append("target_id", targetId);
    setUploading(true);
    try {
      const document = await api<SupportingDocument>("/api/documents", {
        method: "POST",
        body: form,
      });
      onUploaded(document);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Document upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <Button
      component="label"
      disabled={uploading}
      size="small"
      startIcon={<AttachFileRounded />}
    >
      {uploading ? "Uploading…" : "Attach document"}
      <input
        hidden
        type="file"
        accept="image/jpeg,image/png,image/webp,image/heic,image/heif,application/pdf"
        onChange={upload}
      />
    </Button>
  );
}
