import { ChangeEvent, DragEvent, useRef, useState } from "react";
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress, TextField, Typography } from "@mui/material";
import { CloudUploadRounded, InsertDriveFileRounded } from "@mui/icons-material";
import { api } from "../api";

export default function UploadDialog({open, onClose, onUploaded}: {open:boolean; onClose:()=>void; onUploaded:()=>void}) {
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]); const [caption, setCaption] = useState(""); const [dragging, setDragging] = useState(false); const [error, setError] = useState(""); const [loading, setLoading] = useState(false);
  const select = (list: FileList | null) => setFiles(list ? Array.from(list) : []);
  const drop = (event: DragEvent) => {event.preventDefault(); setDragging(false); select(event.dataTransfer.files);};
  const upload = async () => {setLoading(true); setError(""); const body = new FormData(); files.forEach((file) => body.append("files", file)); if (caption) body.append("caption", caption); try {await api("/api/ingestions", {method:"POST", body}); setFiles([]); setCaption(""); onUploaded();} catch(err) {setError(err instanceof Error ? err.message : "Upload failed");} finally {setLoading(false);}};
  return <Dialog open={open} onClose={loading ? undefined : onClose} fullWidth maxWidth="sm"><DialogTitle>Add receipts</DialogTitle><DialogContent sx={{display:"grid", gap:2.5}}>{loading && <LinearProgress />}{error && <Alert severity="error">{error}</Alert>}
    <Box className={`drop-zone ${dragging ? "dragging" : ""}`} onClick={() => input.current?.click()} onDragOver={(e)=>{e.preventDefault();setDragging(true)}} onDragLeave={()=>setDragging(false)} onDrop={drop}><input ref={input} hidden multiple type="file" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,application/pdf" onChange={(e:ChangeEvent<HTMLInputElement>)=>select(e.target.files)} /><CloudUploadRounded color="primary" sx={{fontSize:52}} /><Typography fontWeight={750} sx={{mt:1}}>Drop receipts here</Typography><Typography variant="body2" color="text.secondary">Images, HEIC, or PDF · up to 50 MB each</Typography></Box>
    {files.length > 0 && <Box sx={{display:"grid", gap:1}}>{files.map((file) => <Box key={`${file.name}-${file.size}`} sx={{display:"flex", gap:1, alignItems:"center", p:1.5, borderRadius:3, bgcolor:"action.hover"}}><InsertDriveFileRounded color="action" /><Box sx={{minWidth:0}}><Typography noWrap fontWeight={650}>{file.name}</Typography><Typography variant="caption" color="text.secondary">{(file.size/1024/1024).toFixed(1)} MB</Typography></Box></Box>)}</Box>}
    <TextField label="Context or memo (optional)" multiline minRows={2} value={caption} onChange={(e)=>setCaption(e.target.value)} helperText="This helps classification and is stored with the receipt." />
  </DialogContent><DialogActions sx={{p:2.5}}><Button onClick={onClose} disabled={loading}>Cancel</Button><Button variant="contained" onClick={upload} disabled={!files.length || loading}>Queue {files.length || ""} receipt{files.length === 1 ? "" : "s"}</Button></DialogActions></Dialog>;
}
