import React, { useCallback, useMemo, useRef, useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Divider,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Menu,
  MenuItem,
  Select,
  ListItemIcon,
  ListItemText,
  Breadcrumbs,
  Link,
  LinearProgress,
  Paper,
  Stack,
  Tooltip,
  TextField,
  Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import ArrowForwardIcon from "@mui/icons-material/ArrowForward";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import CreateNewFolderIcon from "@mui/icons-material/CreateNewFolder";
import DeleteOutlinedIcon from "@mui/icons-material/DeleteOutlined";
import DownloadIcon from "@mui/icons-material/Download";
import KeyboardReturnIcon from "@mui/icons-material/KeyboardReturn";
import DriveFileRenameOutlineIcon from "@mui/icons-material/DriveFileRenameOutline";
import FolderIcon from "@mui/icons-material/Folder";
import HomeIcon from "@mui/icons-material/Home";
import InsertDriveFileIcon from "@mui/icons-material/InsertDriveFile";
import RefreshIcon from "@mui/icons-material/Refresh";
import SearchIcon from "@mui/icons-material/Search";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { compactDarkChipSx } from "../../../utils/chipStyles";
import AppSnackbar from "../../../components/AppSnackbar";
import VisibilityIcon from "@mui/icons-material/Visibility";
import VisibilityOffIcon from "@mui/icons-material/VisibilityOff";

function formatBytes(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "";
  const bytes = Number(value);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatModifiedAt(value) {
  if (!value) return "";
  const d = new Date(Number(value) * 1000);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("da-DK", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getUploadFileKey(file) {
  return [file?.name || "", file?.size || 0, file?.lastModified || 0].join("::");
}


function sumFileSizes(files) {
  return Array.from(files || []).reduce((sum, file) => sum + Number(file?.size || 0), 0);
}

function getFileTypeLabel(entry) {
  if (entry?.is_dir) return "Mappe";
  const name = String(entry?.name || "");
  const ext = name.includes(".") ? name.split(".").pop().toUpperCase() : "Fil";
  return ext || "Fil";
}

function shortcutIcon(label) {
  const l = String(label || "").toLowerCase();
  if (l.includes("papirkurv") || l.includes("trash")) return <DeleteOutlinedIcon fontSize="small" />;
  if (l.includes("home") || l.includes("hjem")) return <HomeIcon fontSize="small" />;
  return <FolderIcon fontSize="small" />;
}

function buildVisibleShortcuts(shortcuts) {
  return Array.isArray(shortcuts) ? shortcuts.filter(Boolean) : [];
}

function buildBreadcrumbs(relativePath) {
  const parts = String(relativePath || "")
    .split("/")
    .map((part) => part.trim())
    .filter(Boolean);

  const crumbs = [{ label: "Remote Desktop", path: "" }];
  let current = "";
  parts.forEach((part) => {
    current = current ? `${current}/${part}` : part;
    crumbs.push({ label: part, path: current });
  });
  return crumbs;
}

function sortEntries(entries, sortKey, sortDirection) {
  const direction = sortDirection === "desc" ? -1 : 1;
  const collator = new Intl.Collator("da-DK", { numeric: true, sensitivity: "base" });

  return [...(entries || [])].sort((a, b) => {
    // Finder-lignende: mapper øverst, derefter filer.
    if (!!a.is_dir !== !!b.is_dir) return a.is_dir ? -1 : 1;

    let result = 0;
    if (sortKey === "size") {
      result = Number(a.size_bytes || 0) - Number(b.size_bytes || 0);
    } else if (sortKey === "modified") {
      result = Number(a.modified_at || 0) - Number(b.modified_at || 0);
    } else if (sortKey === "type") {
      result = collator.compare(getFileTypeLabel(a), getFileTypeLabel(b));
    } else {
      result = collator.compare(String(a.name || ""), String(b.name || ""));
    }

    if (result === 0) result = collator.compare(String(a.name || ""), String(b.name || ""));
    return result * direction;
  });
}

function sortLabel(key, activeKey, direction) {
  if (key !== activeKey) return "";
  return direction === "asc" ? " ↑" : " ↓";
}

const CLIENTFLOW_FILE_DRAG_TYPE = "application/x-clientflow-file-paths";

function isInternalFileDrag(event) {
  return Array.from(event?.dataTransfer?.types || []).includes(CLIENTFLOW_FILE_DRAG_TYPE);
}

function getDraggedClientFilePaths(event) {
  try {
    const raw = event?.dataTransfer?.getData(CLIENTFLOW_FILE_DRAG_TYPE) || "[]";
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map((path) => String(path || "").trim()).filter(Boolean) : [];
  } catch {
    return [];
  }
}

function canMovePathsTo(paths, destinationPath) {
  const dest = String(destinationPath || "").trim();
  if (!dest) return false;
  return !Array.from(paths || []).some((raw) => {
    const src = String(raw || "").trim();
    return !src || src === dest || dest.startsWith(`${src}/`);
  });
}

export default function RemoteDesktopFileManager({
  canControl,
  fileInputRef,
  dragOverUpload,
  fileBrowserPath,
  fileBrowserDisplayPath,
  fileBrowserParentPath,
  fileBrowserShortcuts,
  fileBrowserEntries,
  fileBrowserLoading,
  fileBrowserShowHidden,
  fileBrowserError,
  fileDownloadStatus,
  fileDownloadProgress,
  fileDownloadingPath,
  fileOperationBusy,
  fileOperationStatus,
  selectedFilePaths,
  selectedPathSet,
  transferFiles,
  transferUploading,
  transferProgress,
  transferStatus,
  transferError,
  uploadLimitBytes,
  onClearFileBrowserError,
  onClearFileDownloadStatus,
  onClearFileOperationStatus,
  onClearTransferError,
  onClearTransferStatus,
  onClearSelected,
  onSetSelectedPaths,
  onClearTransferFiles,
  onRemoveTransferFile,
  onRequestFileList,
  onRequestSelectedDelete,
  onRequestFileDownload,
  onRequestCreateFolder,
  onRequestRenameEntry,
  onRequestDeleteEntry,
  onRequestMoveEntries,
  onToggleFileSelection,
  onSelectTransferFiles,
  onUploadFilesToClient,
  onUploadDrop,
  onUploadDragEnter,
  onUploadDragOver,
  onUploadDragLeave,
}) {
  const selectedCount = selectedFilePaths.length;
  const transferTotalSize = useMemo(() => sumFileSizes(transferFiles), [transferFiles]);
  const uploadTooLarge = transferTotalSize > uploadLimitBytes;
  const transferStatusSeverity = transferUploading ? "info" : "success";
  const fileDownloadStatusSeverity = fileDownloadingPath ? "info" : "success";
  const fileOperationStatusSeverity = fileOperationBusy ? "info" : "success";
  const uploadProgressValue = Number.isFinite(Number(transferProgress?.percent)) ? Number(transferProgress.percent) : null;
  const downloadProgressValue = Number.isFinite(Number(fileDownloadProgress?.percent)) ? Number(fileDownloadProgress.percent) : null;

  const [sortKey, setSortKey] = useState("name");
  const [sortDirection, setSortDirection] = useState("asc");
  const [searchQuery, setSearchQuery] = useState("");
  const [contextMenu, setContextMenu] = useState(null);
  const [emptyContextMenu, setEmptyContextMenu] = useState(null);
  const [navHistory, setNavHistory] = useState([fileBrowserPath || ""]);
  const [navIndex, setNavIndex] = useState(0);
  const [lastSelectedPath, setLastSelectedPath] = useState(null);
  const [inlineRenamePath, setInlineRenamePath] = useState(null);
  const [inlineRenameValue, setInlineRenameValue] = useState("");
  const [uploadConflictStrategies, setUploadConflictStrategies] = useState({});
  const [uploadConflictDialogOpen, setUploadConflictDialogOpen] = useState(false);
  const [dragMoveOverPath, setDragMoveOverPath] = useState("");
  const renameInputRef = useRef(null);

  const breadcrumbs = useMemo(() => buildBreadcrumbs(fileBrowserPath), [fileBrowserPath]);
  const visibleShortcuts = useMemo(() => buildVisibleShortcuts(fileBrowserShortcuts), [fileBrowserShortcuts]);
  const filteredEntries = useMemo(() => {
    const query = String(searchQuery || "").trim().toLowerCase();
    return (fileBrowserEntries || []).filter((entry) => {
      if (!fileBrowserShowHidden && entry?.hidden) return false;
      if (!query) return true;
      return (
        String(entry?.name || "").toLowerCase().includes(query) ||
        getFileTypeLabel(entry).toLowerCase().includes(query)
      );
    });
  }, [fileBrowserEntries, fileBrowserShowHidden, searchQuery]);

  const sortedEntries = useMemo(
    () => sortEntries(filteredEntries, sortKey, sortDirection),
    [filteredEntries, sortDirection, sortKey]
  );
  const existingEntryNames = useMemo(
    () => new Set((fileBrowserEntries || []).map((entry) => String(entry.name || ""))),
    [fileBrowserEntries]
  );
  const selectableEntries = useMemo(() => sortedEntries.filter((entry) => !!entry?.relative_path), [sortedEntries]);
  const selectedVisibleCount = useMemo(
    () => selectableEntries.filter((entry) => selectedPathSet.has(entry.relative_path || "")).length,
    [selectableEntries, selectedPathSet]
  );
  const allVisibleSelected = selectableEntries.length > 0 && selectedVisibleCount === selectableEntries.length;

  const activeContextEntry = contextMenu?.entry || null;
  const canGoBack = navIndex > 0;
  const canGoForward = navIndex < navHistory.length - 1;

  const navigateTo = useCallback((path = "", showHidden = fileBrowserShowHidden, pushHistory = true) => {
    const nextPath = String(path || "");
    if (pushHistory) {
      setNavHistory((prev) => {
        const base = prev.slice(0, navIndex + 1);
        if (base[base.length - 1] === nextPath) return base;
        return [...base, nextPath];
      });
      setNavIndex((prev) => {
        const current = navHistory.slice(0, prev + 1);
        return current[current.length - 1] === nextPath ? prev : prev + 1;
      });
    }
    onClearSelected?.();
    onRequestFileList(nextPath, showHidden);
  }, [fileBrowserShowHidden, navHistory, navIndex, onClearSelected, onRequestFileList]);

  const goBack = useCallback(() => {
    if (!canGoBack) return;
    const nextIndex = navIndex - 1;
    setNavIndex(nextIndex);
    onClearSelected?.();
    onRequestFileList(navHistory[nextIndex] || "", fileBrowserShowHidden);
  }, [canGoBack, fileBrowserShowHidden, navHistory, navIndex, onClearSelected, onRequestFileList]);

  const goForward = useCallback(() => {
    if (!canGoForward) return;
    const nextIndex = navIndex + 1;
    setNavIndex(nextIndex);
    onClearSelected?.();
    onRequestFileList(navHistory[nextIndex] || "", fileBrowserShowHidden);
  }, [canGoForward, fileBrowserShowHidden, navHistory, navIndex, onClearSelected, onRequestFileList]);

  const setUploadConflictStrategy = useCallback((file, strategy) => {
    const key = getUploadFileKey(file);
    setUploadConflictStrategies((prev) => ({ ...prev, [key]: strategy || "keep_both" }));
  }, []);

  const startUpload = useCallback(() => {
    if (!Array.from(transferFiles || []).length || transferUploading || uploadTooLarge) return;
    setUploadConflictDialogOpen(true);
  }, [transferFiles, transferUploading, uploadTooLarge]);

  const confirmUploadWithConflictStrategies = useCallback(() => {
    const strategiesByIndex = {};
    Array.from(transferFiles || []).forEach((file, index) => {
      strategiesByIndex[index] = uploadConflictStrategies[getUploadFileKey(file)] || "keep_both";
    });

    setUploadConflictDialogOpen(false);
    onUploadFilesToClient(strategiesByIndex);
  }, [onUploadFilesToClient, transferFiles, uploadConflictStrategies]);

  const addFilesToUploadList = useCallback((filesLike) => {
    if (!transferUploading) {
      setUploadConflictDialogOpen(false);
    }
    onSelectTransferFiles(filesLike || []);
  }, [onSelectTransferFiles, transferUploading]);

  const handleUploadDropInZone = useCallback((event) => {
    if (!transferUploading) {
      setUploadConflictDialogOpen(false);
    }
    onUploadDrop?.(event);
  }, [onUploadDrop, transferUploading]);

  const toggleAllVisible = useCallback(() => {
    if (!selectableEntries.length || !canControl || fileBrowserLoading || fileOperationBusy) return;
    if (allVisibleSelected) {
      onClearSelected();
      return;
    }
    const paths = selectableEntries.map((entry) => entry.relative_path || "").filter(Boolean);
    if (typeof onSetSelectedPaths === "function") {
      onSetSelectedPaths(paths);
    } else {
      paths.forEach((path) => {
        if (!selectedPathSet.has(path)) {
          const entry = selectableEntries.find((item) => item.relative_path === path);
          if (entry) onToggleFileSelection(entry);
        }
      });
    }
  }, [allVisibleSelected, canControl, fileBrowserLoading, fileOperationBusy, onClearSelected, onSetSelectedPaths, onToggleFileSelection, selectableEntries, selectedPathSet]);

  const handleFileListKeyDown = useCallback((event) => {
    const tag = String(event.target?.tagName || "").toLowerCase();
    if (["input", "textarea", "select"].includes(tag)) return;

    if ((event.ctrlKey || event.metaKey) && String(event.key || "").toLowerCase() === "a") {
      event.preventDefault();
      toggleAllVisible();
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      setContextMenu(null);
      setEmptyContextMenu(null);
      setInlineRenamePath(null);
      onClearSelected?.();
      return;
    }

    if ((event.key === "Delete" || event.key === "Backspace") && selectedCount > 0) {
      event.preventDefault();
      onRequestSelectedDelete?.();
      return;
    }

    if (event.key === "ArrowLeft" && (event.altKey || event.metaKey)) {
      event.preventDefault();
      goBack();
      return;
    }

    if (event.key === "ArrowRight" && (event.altKey || event.metaKey)) {
      event.preventDefault();
      goForward();
    }
  }, [goBack, goForward, onClearSelected, onRequestSelectedDelete, selectedCount, toggleAllVisible]);

  const toggleSort = useCallback((key) => {
    setSortKey((prevKey) => {
      if (prevKey === key) {
        setSortDirection((prevDirection) => (prevDirection === "asc" ? "desc" : "asc"));
        return prevKey;
      }
      setSortDirection(key === "modified" ? "desc" : "asc");
      return key;
    });
  }, []);

  const openEntry = useCallback((entry) => {
    if (!entry || !canControl || fileBrowserLoading || fileOperationBusy) return;
    if (entry.is_dir) {
      navigateTo(entry.relative_path || "");
    } else {
      onRequestFileDownload(entry);
    }
  }, [canControl, fileBrowserLoading, fileOperationBusy, navigateTo, onRequestFileDownload]);

  const setSingleSelection = useCallback((path) => {
    if (typeof onSetSelectedPaths === "function") {
      onSetSelectedPaths(path ? [path] : []);
    } else {
      const entry = selectableEntries.find((item) => item.relative_path === path);
      if (entry && !selectedPathSet.has(path)) onToggleFileSelection(entry);
    }
  }, [onSetSelectedPaths, onToggleFileSelection, selectableEntries, selectedPathSet]);

  const selectEntryFromEvent = useCallback((event, entry) => {
    const path = entry?.relative_path || "";
    if (!path || entry?.is_dir) return;

    if (event.shiftKey && lastSelectedPath && typeof onSetSelectedPaths === "function") {
      const paths = selectableEntries.map((item) => item.relative_path || "").filter(Boolean);
      const start = paths.indexOf(lastSelectedPath);
      const end = paths.indexOf(path);
      if (start >= 0 && end >= 0) {
        const [from, to] = start <= end ? [start, end] : [end, start];
        const range = paths.slice(from, to + 1);
        const next = Array.from(new Set([...(selectedFilePaths || []), ...range]));
        onSetSelectedPaths(next);
        return;
      }
    }

    if (event.ctrlKey || event.metaKey) {
      onToggleFileSelection(entry);
      setLastSelectedPath(path);
      return;
    }

    setSingleSelection(path);
    setLastSelectedPath(path);
  }, [lastSelectedPath, onSetSelectedPaths, onToggleFileSelection, selectableEntries, selectedFilePaths, setSingleSelection]);

  const startInlineRename = useCallback((entry) => {
    if (!entry || !canControl || fileOperationBusy || fileBrowserLoading) return;
    setInlineRenamePath(entry.relative_path || "");
    setInlineRenameValue(entry.name || "");
    window.setTimeout(() => {
      try { renameInputRef.current?.focus?.(); renameInputRef.current?.select?.(); } catch {}
    }, 30);
  }, [canControl, fileBrowserLoading, fileOperationBusy]);

  const commitInlineRename = useCallback((entry) => {
    if (!entry || inlineRenamePath !== (entry.relative_path || "")) return;
    const nextName = String(inlineRenameValue || "").trim();
    setInlineRenamePath(null);
    if (!nextName || nextName === entry.name) return;
    onRequestRenameEntry(entry, nextName);
  }, [inlineRenamePath, inlineRenameValue, onRequestRenameEntry]);

  const openEmptyContextMenu = useCallback((event) => {
    if (event.target?.closest?.('[data-file-row="true"]')) return;
    event.preventDefault();
    setEmptyContextMenu({ mouseX: event.clientX + 2, mouseY: event.clientY - 6 });
  }, []);

  const openContextMenu = useCallback((event, entry) => {
    event.preventDefault();
    event.stopPropagation();
    if (!entry) return;
    setContextMenu({ mouseX: event.clientX + 2, mouseY: event.clientY - 6, entry });
  }, []);

  const closeContextMenu = useCallback(() => {
    setContextMenu(null);
    setEmptyContextMenu(null);
  }, []);

  const handleContextAction = useCallback((action) => {
    const entry = activeContextEntry;
    closeContextMenu();
    if (!entry) return;
    if (action === "open") openEntry(entry);
    if (action === "download") onRequestFileDownload(entry);
    if (action === "rename") startInlineRename(entry);
    if (action === "delete") onRequestDeleteEntry(entry);
  }, [activeContextEntry, closeContextMenu, onRequestDeleteEntry, onRequestFileDownload, openEntry, startInlineRename]);

  const handleClientFileDragStart = useCallback((event, entry) => {
    const path = entry?.relative_path || "";
    if (!path || !canControl || fileOperationBusy || fileBrowserLoading) return;
    const paths = selectedPathSet.has(path) && selectedFilePaths.length > 0
      ? selectedFilePaths
      : [path];
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData(CLIENTFLOW_FILE_DRAG_TYPE, JSON.stringify(paths));
    event.dataTransfer.setData("text/plain", paths.join("\n"));
  }, [canControl, fileBrowserLoading, fileOperationBusy, selectedFilePaths, selectedPathSet]);

  const handleFolderDragOver = useCallback((event, destinationEntryOrPath) => {
    const destinationPath = typeof destinationEntryOrPath === "string"
      ? destinationEntryOrPath
      : destinationEntryOrPath?.relative_path || "";
    if (!canControl || fileOperationBusy || fileBrowserLoading || !destinationPath || !isInternalFileDrag(event)) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    setDragMoveOverPath(destinationPath);
  }, [canControl, fileBrowserLoading, fileOperationBusy]);

  const handleFolderDragLeave = useCallback((event, destinationPath) => {
    if (!destinationPath) return;
    const currentTarget = event.currentTarget;
    const related = event.relatedTarget;
    if (currentTarget && related && currentTarget.contains(related)) return;
    setDragMoveOverPath((prev) => (prev === destinationPath ? "" : prev));
  }, []);

  const handleFolderDrop = useCallback((event, destinationEntryOrPath) => {
    const destinationPath = typeof destinationEntryOrPath === "string"
      ? destinationEntryOrPath
      : destinationEntryOrPath?.relative_path || "";
    if (!canControl || fileOperationBusy || fileBrowserLoading || !destinationPath || !isInternalFileDrag(event)) return;
    event.preventDefault();
    event.stopPropagation();
    const paths = getDraggedClientFilePaths(event);
    setDragMoveOverPath("");
    if (!paths.length || !canMovePathsTo(paths, destinationPath)) return;
    onRequestMoveEntries?.(paths, destinationPath);
  }, [canControl, fileBrowserLoading, fileOperationBusy, onRequestMoveEntries]);

  const handleRowKeyDown = useCallback((event, entry) => {
    if (!entry) return;
    if (event.key === "Enter") {
      event.preventDefault();
      openEntry(entry);
    }
    if ((event.key === " " || event.key === "Spacebar") && !entry.is_dir) {
      event.preventDefault();
      onToggleFileSelection(entry);
    }
  }, [onToggleFileSelection, openEntry]);

  const columnHeaderSx = {
    borderRadius: 1.4,
    px: 0.5,
    py: 0.25,
    cursor: "pointer",
    userSelect: "none",
    fontWeight: 900,
    "&:hover": { bgcolor: "rgba(148,163,184,0.10)" },
  };

  return (
    <Paper
      elevation={0}
      sx={{
        borderRadius: 2,
        overflow: "hidden",
        bgcolor: "rgba(15,23,42,0.72)",
        border: "1px solid rgba(148,163,184,0.16)",
        boxShadow: "0 24px 80px rgba(0,0,0,0.24)",
      }}
    >
      <AppSnackbar
        open={Boolean(transferError)}
        message={transferError}
        severity="error"
        onClose={onClearTransferError}
      />
      <AppSnackbar
        open={Boolean(transferStatus)}
        message={transferStatus}
        severity={transferStatusSeverity}
        onClose={onClearTransferStatus}
      />
      <AppSnackbar
        open={Boolean(fileDownloadStatus)}
        message={fileDownloadStatus}
        severity={fileDownloadStatusSeverity}
        onClose={onClearFileDownloadStatus}
      />
      <AppSnackbar
        open={Boolean(fileOperationStatus)}
        message={fileOperationStatus}
        severity={fileOperationStatusSeverity}
        onClose={onClearFileOperationStatus}
      />
      <AppSnackbar
        open={Boolean(fileBrowserError)}
        message={fileBrowserError}
        severity="error"
        onClose={onClearFileBrowserError}
      />

      {(transferUploading || fileDownloadingPath) && (
        <Box sx={{ px: { xs: 1.3, md: 1.8 }, pt: 1.25 }}>
          <Stack spacing={0.75}>
            {transferUploading && (
              <Box>
                <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", mb: 0.35 }}>
                  <Typography variant="caption" sx={{ fontWeight: 900 }}>Filupload</Typography>
                  <Typography variant="caption" sx={{ color: "text.secondary" }}>
                    {uploadProgressValue !== null ? `${uploadProgressValue}%` : "I gang"}
                  </Typography>
                </Stack>
                <LinearProgress
                  variant={uploadProgressValue !== null ? "determinate" : "indeterminate"}
                  value={uploadProgressValue ?? undefined}
                  aria-label="Filupload progress"
                  sx={{ height: 7, borderRadius: 999 }}
                />
              </Box>
            )}
            {fileDownloadingPath && (
              <Box>
                <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", mb: 0.35 }}>
                  <Typography variant="caption" sx={{ fontWeight: 900 }}>Fildownload</Typography>
                  <Typography variant="caption" sx={{ color: "text.secondary" }}>
                    {downloadProgressValue !== null ? `${downloadProgressValue}%` : "I gang"}
                  </Typography>
                </Stack>
                <LinearProgress
                  variant={downloadProgressValue !== null ? "determinate" : "indeterminate"}
                  value={downloadProgressValue ?? undefined}
                  aria-label="Fildownload progress"
                  sx={{ height: 7, borderRadius: 999 }}
                />
              </Box>
            )}
          </Stack>
        </Box>
      )}
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", lg: "240px minmax(0, 1fr)" },
          minHeight: { xs: 620, lg: "calc(100vh - 210px)" },
        }}
      >
        <Box
          sx={{
            p: { xs: 1.4, md: 1.7 },
            bgcolor: "rgba(2,6,23,0.42)",
            borderRight: { xs: "none", lg: "1px solid rgba(148,163,184,0.14)" },
            borderBottom: { xs: "1px solid rgba(148,163,184,0.14)", lg: "none" },
          }}
        >
          <Stack spacing={1.4}>
            <Box>
              <Typography variant="overline" sx={{ color: "rgba(125,211,252,0.82)", fontWeight: 950, letterSpacing: 0.9 }}>
                Klientfiler
              </Typography>
              <Typography variant="h6" sx={{ fontWeight: 950, lineHeight: 1.1 }}>
                Filer
              </Typography>
              <Typography variant="caption" sx={{
                color: "text.secondary"
              }}>
                Finder-inspireret filhåndtering i Remote Desktops isolerede filområde.
              </Typography>
              <Typography
                variant="caption"
                sx={{
                  color: "text.secondary",
                  display: "block",
                  mt: 0.45
                }}>
                Træk filer eller mapper over på en mappe for at flytte dem.
              </Typography>
            </Box>

            <Divider />

            <Box>
              <Typography
                variant="caption"
                sx={{
                  color: "text.secondary",
                  display: "block",
                  mb: 0.8,
                  fontWeight: 850
                }}>
                Favoritter
              </Typography>
              <Stack spacing={0.65}>
                {visibleShortcuts.map((shortcut) => {
                  const active = (fileBrowserPath || "") === (shortcut.path || "");
                  const shortcutIsTrash = String(shortcut.label || "").toLowerCase().includes("papirkurv") || String(shortcut.label || "").toLowerCase().includes("trash");
                  return (
                    <Button
                      key={`${shortcut.label}-${shortcut.path}`}
                      startIcon={shortcutIcon(shortcut.label)}
                      variant={active ? "contained" : "text"}
                      color={active ? "primary" : "inherit"}
                      disabled={!canControl || fileBrowserLoading}
                      onClick={() => navigateTo(shortcut.path || "")}
                      onDragOver={(event) => !shortcutIsTrash && handleFolderDragOver(event, shortcut.path || "")}
                      onDragLeave={(event) => !shortcutIsTrash && handleFolderDragLeave(event, shortcut.path || "")}
                      onDrop={(event) => !shortcutIsTrash && handleFolderDrop(event, shortcut.path || "")}
                      sx={{
                        justifyContent: "flex-start",
                        borderRadius: 2,
                        textTransform: "none",
                        fontWeight: active ? 900 : 750,
                      }}
                      fullWidth
                    >
                      {shortcut.label}
                    </Button>
                  );
                })}
              </Stack>
            </Box>

            <Divider />

            <Box>
              <Typography
                variant="caption"
                sx={{
                  color: "text.secondary",
                  display: "block",
                  mb: 0.8,
                  fontWeight: 850
                }}>
                Upload
              </Typography>
              <Box
                onDrop={handleUploadDropInZone}
                onDragEnter={onUploadDragEnter}
                onDragOver={onUploadDragOver}
                onDragLeave={onUploadDragLeave}
                sx={{
                  px: 1.4,
                  py: 3.2,
                  minHeight: 230,
                  borderRadius: 2,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  textAlign: "center",
                  bgcolor: dragOverUpload ? "rgba(14,165,233,0.18)" : "rgba(15,23,42,0.48)",
                  border: dragOverUpload ? "2px dashed rgba(125,211,252,0.95)" : "2px dashed rgba(148,163,184,0.32)",
                  transition: "background 120ms ease, border-color 120ms ease, transform 120ms ease",
                  transform: dragOverUpload ? "scale(1.01)" : "scale(1)",
                }}
              >
                <UploadFileIcon sx={{ fontSize: 34, mb: 0.7, opacity: 0.86 }} />
                <Typography variant="body1" sx={{ fontWeight: 950, color: uploadTooLarge ? "error.main" : dragOverUpload ? "primary.main" : "text.primary" }}>
                  {dragOverUpload ? "Slip filer her" : "Træk filer hertil"}
                </Typography>
                <Typography variant="caption" sx={{ display: "block", mt: 0.45, color: uploadTooLarge ? "error.main" : "text.secondary" }}>
                  {transferFiles.length ? `${transferFiles.length} valgt · ${formatBytes(transferTotalSize)} / ${formatBytes(uploadLimitBytes)}` : `Upload til aktuel mappe · maks ${formatBytes(uploadLimitBytes)} i alt`}
                </Typography>
              </Box>

              <input
                ref={fileInputRef}
                type="file"
                hidden
                multiple
                onChange={(e) => {
                  addFilesToUploadList(e.target.files || []);
                  e.target.value = "";
                }}
              />

              {transferFiles.length > 0 && (
                <Box
                  sx={{
                    mt: 1,
                    p: 1,
                    borderRadius: 2,
                    bgcolor: "rgba(2,6,23,0.35)",
                    border: "1px solid rgba(148,163,184,0.14)",
                    maxHeight: 220,
                    overflow: "auto",
                  }}
                >
                  <Stack
                    direction="row"
                    sx={{
                      alignItems: "center",
                      justifyContent: "space-between",
                      mb: 0.75
                    }}>
                    <Typography
                      variant="caption"
                      sx={{
                        color: "text.secondary",
                        fontWeight: 900
                      }}>
                      Uploadliste
                    </Typography>
                    <Chip size="small" label={`${transferFiles.length} fil(er)`} sx={compactDarkChipSx("neutral")} />
                  </Stack>
                  <Stack spacing={0.55}>
                    {Array.from(transferFiles).map((file, index) => (
                      <Stack
                        key={`${index}-${file.name}-${file.size}-${file.lastModified || 0}`}
                        direction="row"
                        spacing={0.75}
                        sx={{
                          alignItems: "center",
                          minWidth: 0,
                          px: 0.65,
                          py: 0.55,
                          borderRadius: 1.5,
                          bgcolor: "rgba(15,23,42,0.42)",
                          border: "1px solid rgba(148,163,184,0.10)"
                        }}>
                        <InsertDriveFileIcon fontSize="small" sx={{ opacity: 0.72, flex: "0 0 auto" }} />
                        <Box sx={{ flex: 1, minWidth: 0 }}>
                          <Typography variant="caption" sx={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 750 }} title={file.name}>
                            {file.name}
                          </Typography>
                        </Box>
                        <Typography
                          variant="caption"
                          sx={{
                            color: "text.secondary",
                            flex: "0 0 auto"
                          }}>
                          {formatBytes(file.size)}
                        </Typography>
                        <Tooltip title="Fjern fra uploadliste">
                          <span>
                            <Button
                              size="small"
                              color="error"
                              variant="text"
                              disabled={transferUploading}
                              onClick={() => onRemoveTransferFile?.(index)}
                              sx={{ minWidth: 28, px: 0.35 }}
                            >
                              <DeleteOutlinedIcon fontSize="small" />
                            </Button>
                          </span>
                        </Tooltip>
                      </Stack>
                    ))}
                  </Stack>
                </Box>
              )}

              <Stack direction="row" spacing={0.75} sx={{ mt: 1 }}>
                <Button
                  size="small"
                  startIcon={<UploadFileIcon />}
                  disabled={!canControl || transferUploading}
                  variant="outlined"
                  onClick={() => fileInputRef.current?.click()}
                  sx={{ textTransform: "none", flex: 1 }}
                >
                  Vælg
                </Button>
                <Button
                  size="small"
                  disabled={!canControl || !transferFiles.length || transferUploading || uploadTooLarge}
                  variant="contained"
                  onClick={startUpload}
                  sx={{ textTransform: "none", flex: 1 }}
                >
                  {transferUploading ? <CircularProgress size={16} color="inherit" /> : "Upload"}
                </Button>
              </Stack>

              {transferFiles.length > 0 && !transferUploading && (
                <Button
                  size="small"
                  color="inherit"
                  variant="text"
                  onClick={onClearTransferFiles}
                  sx={{ mt: 0.6, textTransform: "none" }}
                  fullWidth
                >
Ryd hele uploadlisten
                </Button>
              )}
            </Box>

          </Stack>
        </Box>

        <Box sx={{ minWidth: 0, display: "flex", flexDirection: "column" }}>
          <Box sx={{ px: { xs: 1.3, md: 1.8 }, py: 1.4, borderBottom: "1px solid rgba(148,163,184,0.14)", bgcolor: "rgba(15,23,42,0.52)" }}>
            <Stack spacing={1.1}>
              <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{
                alignItems: { xs: "stretch", md: "center" }
              }}>
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography
                    variant="caption"
                    sx={{
                      color: "text.secondary",
                      display: "block",
                      mb: 0.25
                    }}>
                    Aktuel mappe
                  </Typography>
                  <Breadcrumbs
                    maxItems={5}
                    aria-label="filsti"
                    sx={{
                      color: "rgba(226,232,240,0.92)",
                      "& .MuiBreadcrumbs-separator": { color: "rgba(148,163,184,0.7)" },
                    }}
                  >
                    {breadcrumbs.map((crumb, index) => {
                      const last = index === breadcrumbs.length - 1;
                      return last ? (
                        <Typography key={crumb.path || "home"} variant="body1" sx={{ fontWeight: 950 }} title={fileBrowserDisplayPath || "/home"}>
                          {crumb.label}
                        </Typography>
                      ) : (
                        <Link
                          key={crumb.path || "home"}
                          component="button"
                          underline="hover"
                          color="inherit"
                          disabled={!canControl || fileBrowserLoading}
                          onClick={() => navigateTo(crumb.path)}
                          sx={{ fontWeight: 850, cursor: "pointer" }}
                        >
                          {crumb.label}
                        </Link>
                      );
                    })}
                  </Breadcrumbs>
                  <Typography
                    variant="caption"
                    title={fileBrowserDisplayPath || "/home"}
                    sx={{
                      color: "text.secondary",
                      display: "block",
                      mt: 0.15,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap"
                    }}>
                    {fileBrowserDisplayPath || "/home"}
                  </Typography>
                </Box>

                <Stack direction="row" spacing={0.7} sx={{ flexWrap: "wrap", rowGap: 0.7 }}>
                  <Button disabled={!canControl || fileBrowserLoading || !canGoBack} size="small" variant="outlined" color="inherit" onClick={goBack} sx={{ minWidth: 36, px: 0.9 }}>
                    <ArrowBackIcon fontSize="small" />
                  </Button>
                  <Button disabled={!canControl || fileBrowserLoading || !canGoForward} size="small" variant="outlined" color="inherit" onClick={goForward} sx={{ minWidth: 36, px: 0.9 }}>
                    <ArrowForwardIcon fontSize="small" />
                  </Button>
                  <Button disabled={!canControl || fileBrowserLoading || !selectableEntries.length || fileOperationBusy} size="small" variant={allVisibleSelected ? "contained" : "outlined"} color={allVisibleSelected ? "primary" : "inherit"} onClick={toggleAllVisible}>
                    {allVisibleSelected ? "Ryd valg" : "Vælg alle"}
                  </Button>
                  <Button disabled={!canControl || fileBrowserLoading || !fileBrowserPath} size="small" startIcon={<ArrowUpwardIcon />} variant="outlined" color="inherit" onClick={() => navigateTo(fileBrowserParentPath || "")}>
                    Op
                  </Button>
                  <Button disabled={!canControl || fileBrowserLoading} size="small" startIcon={<RefreshIcon />} variant="outlined" onClick={() => onRequestFileList(fileBrowserPath || "")}>
                    {fileBrowserLoading ? <CircularProgress size={16} color="inherit" /> : "Opdater"}
                  </Button>
                  <Button disabled={!canControl || fileBrowserLoading} size="small" startIcon={fileBrowserShowHidden ? <VisibilityOffIcon /> : <VisibilityIcon />} variant={fileBrowserShowHidden ? "contained" : "outlined"} color={fileBrowserShowHidden ? "warning" : "inherit"} onClick={() => onRequestFileList(fileBrowserPath || "", !fileBrowserShowHidden)}>
                    {fileBrowserShowHidden ? "Skjul skjulte" : "Vis skjulte"}
                  </Button>
                  <Button disabled={!canControl || fileOperationBusy || fileBrowserLoading} size="small" startIcon={<CreateNewFolderIcon />} variant="outlined" onClick={onRequestCreateFolder}>
                    Ny mappe
                  </Button>
                </Stack>
              </Stack>

              <TextField
                size="small"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Søg i aktuel mappe"
                disabled={!canControl || fileBrowserLoading}
                sx={{ maxWidth: 420 }}
                slotProps={{
                  input: { startAdornment: <SearchIcon fontSize="small" sx={{ mr: 0.75, color: "text.secondary" }} /> }
                }}
              />

              {selectedCount > 0 && (
                <Paper
                  variant="outlined"
                  sx={{
                    px: 1.25,
                    py: 0.8,
                    borderRadius: 2,
                    bgcolor: "rgba(14,165,233,0.10)",
                    borderColor: "rgba(125,211,252,0.28)",
                  }}
                >
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{
                    alignItems: { xs: "stretch", sm: "center" }
                  }}>
                    <Typography variant="body2" sx={{ flex: 1 }}>
                      {selectedCount} element(er) valgt
                    </Typography>
                    <Button size="small" startIcon={<DeleteOutlinedIcon />} variant="outlined" color="error" disabled={!canControl || fileOperationBusy || fileBrowserLoading} onClick={onRequestSelectedDelete}>
                      Slet valgte permanent
                    </Button>
                    <Button size="small" variant="outlined" color="inherit" onClick={onClearSelected}>
                      Ryd valg
                    </Button>
                  </Stack>
                </Paper>
              )}
            </Stack>
          </Box>

          <Box sx={{ flex: 1, minHeight: 0, overflow: "auto", outline: "none" }} tabIndex={0} onKeyDown={handleFileListKeyDown} onContextMenu={openEmptyContextMenu}>
            <Box
              sx={{
                display: { xs: "none", md: "grid" },
                gridTemplateColumns: "48px minmax(260px, 1fr) 110px 110px 150px 250px",
                gap: 1,
                alignItems: "center",
                px: 1.4,
                py: 0.8,
                bgcolor: "rgba(2,6,23,0.36)",
                borderBottom: "1px solid rgba(148,163,184,0.12)",
                position: "sticky",
                top: 0,
                zIndex: 1,
              }}
            >
              <Tooltip title={allVisibleSelected ? "Ryd valg" : "Vælg alle synlige"}>
                <span>
                  <Checkbox
                    size="small"
                    checked={allVisibleSelected}
                    indeterminate={selectedVisibleCount > 0 && !allVisibleSelected}
                    disabled={!canControl || fileBrowserLoading || fileOperationBusy || !selectableEntries.length}
                    onChange={toggleAllVisible}
                    sx={{ p: 0.2 }}
                  />
                </span>
              </Tooltip>
              <Typography
                variant="caption"
                onClick={() => toggleSort("name")}
                sx={[{
                  color: "text.secondary"
                }, ...(Array.isArray(columnHeaderSx) ? columnHeaderSx : [columnHeaderSx])]}>Navn{sortLabel("name", sortKey, sortDirection)}</Typography>
              <Typography
                variant="caption"
                onClick={() => toggleSort("type")}
                sx={[{
                  color: "text.secondary"
                }, ...(Array.isArray(columnHeaderSx) ? columnHeaderSx : [columnHeaderSx])]}>Type{sortLabel("type", sortKey, sortDirection)}</Typography>
              <Typography
                variant="caption"
                onClick={() => toggleSort("size")}
                sx={[{
                  color: "text.secondary"
                }, ...(Array.isArray(columnHeaderSx) ? columnHeaderSx : [columnHeaderSx])]}>Størrelse{sortLabel("size", sortKey, sortDirection)}</Typography>
              <Typography
                variant="caption"
                onClick={() => toggleSort("modified")}
                sx={[{
                  color: "text.secondary"
                }, ...(Array.isArray(columnHeaderSx) ? columnHeaderSx : [columnHeaderSx])]}>Ændret{sortLabel("modified", sortKey, sortDirection)}</Typography>
              <Typography
                variant="caption"
                sx={{
                  color: "text.secondary",
                  fontWeight: 900,
                  textAlign: "right"
                }}>Handlinger</Typography>
            </Box>

            {fileBrowserLoading && !fileBrowserEntries.length ? (
              <Box sx={{ p: 2, display: "flex", gap: 1, alignItems: "center" }}>
                <CircularProgress size={18} color="inherit" />
                <Typography variant="body2">Henter filliste fra klienten...</Typography>
              </Box>
            ) : sortedEntries.length === 0 ? (
              <Box sx={{ p: 3 }}>
                <Typography variant="body2" sx={{
                  color: "text.secondary"
                }}>Ingen filer eller mapper at vise.</Typography>
                <Typography variant="caption" sx={{
                  color: "text.secondary"
                }}>
                  Brug “Vis skjulte”, hvis mappen starter med punktum, eller vælg en genvej i sidebaren.
                </Typography>
              </Box>
            ) : (
              <Stack divider={<Divider flexItem /> }>
                {sortedEntries.map((entry) => {
                  const selected = selectedPathSet.has(entry.relative_path || "");
                  const busyThis = fileDownloadingPath === entry.relative_path;
                  return (
                    <Box
                      key={entry.relative_path || entry.name}
                      role="button"
                      data-file-row="true"
                      tabIndex={0}
                      draggable={!!entry.relative_path && canControl && !fileOperationBusy && !fileBrowserLoading}
                      onDragStart={(event) => handleClientFileDragStart(event, entry)}
                      onDragEnd={() => setDragMoveOverPath("")}
                      onDragOver={(event) => entry.is_dir && handleFolderDragOver(event, entry)}
                      onDragLeave={(event) => entry.is_dir && handleFolderDragLeave(event, entry.relative_path || "")}
                      onDrop={(event) => entry.is_dir && handleFolderDrop(event, entry)}
                      onKeyDown={(event) => handleRowKeyDown(event, entry)}
                      onContextMenu={(event) => openContextMenu(event, entry)}
                      onDoubleClick={() => openEntry(entry)}
                      onClick={(event) => {
                        if (event.target?.closest?.("button") || event.target?.closest?.("input")) return;
                        if (entry.is_dir) {
                          openEntry(entry);
                        } else {
                          selectEntryFromEvent(event, entry);
                        }
                      }}
                      sx={{
                        display: "grid",
                        gridTemplateColumns: { xs: "40px minmax(0, 1fr)", md: "48px minmax(260px, 1fr) 110px 110px 150px 250px" },
                        gap: 1,
                        alignItems: "center",
                        px: 1.4,
                        py: 0.8,
                        bgcolor: dragMoveOverPath === (entry.relative_path || "")
                          ? "rgba(34,197,94,0.16)"
                          : selected
                          ? "rgba(14,165,233,0.10)"
                          : "transparent",
                        opacity: entry.hidden ? 0.72 : 1,
                        cursor: entry.is_dir ? "pointer" : "default",
                        outline: "none",
                        "&:focus-visible": { boxShadow: "inset 0 0 0 2px rgba(56,189,248,0.75)" },
                        "&:hover": { bgcolor: selected ? "rgba(14,165,233,0.16)" : "rgba(148,163,184,0.06)" },
                      }}
                    >
                      <Checkbox
                        size="small"
                        checked={selected}
                        disabled={!canControl || fileOperationBusy || fileBrowserLoading}
                        onClick={(event) => event.stopPropagation()}
                        onChange={() => onToggleFileSelection(entry)}
                        sx={{ p: 0.4 }}
                      />
                      <Stack
                        direction="row"
                        spacing={1}
                        sx={{
                          alignItems: "center",
                          minWidth: 0
                        }}>
                        {entry.is_dir ? <FolderIcon color="primary" /> : <InsertDriveFileIcon color="inherit" />}
                        <Box sx={{ minWidth: 0 }}>
                          {inlineRenamePath === (entry.relative_path || "") ? (
                            <TextField
                              slotProps={{ htmlInput: { ref: renameInputRef } }}
                              size="small"
                              value={inlineRenameValue}
                              onChange={(event) => setInlineRenameValue(event.target.value)}
                              onClick={(event) => event.stopPropagation()}
                              onKeyDown={(event) => {
                                if (event.key === "Enter") {
                                  event.preventDefault();
                                  commitInlineRename(entry);
                                }
                                if (event.key === "Escape") {
                                  event.preventDefault();
                                  setInlineRenamePath(null);
                                }
                              }}
                              onBlur={() => commitInlineRename(entry)}
                              sx={{ maxWidth: 360 }}
                            />
                          ) : (
                            <Typography variant="body2" sx={{ fontWeight: entry.is_dir ? 900 : 650, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={entry.name}>
                              {entry.name}{entry.hidden ? " · skjult" : ""}
                            </Typography>
                          )}
                          <Typography
                            variant="caption"
                            sx={{
                              color: "text.secondary",
                              display: { xs: "block", md: "none" }
                            }}>
                            {getFileTypeLabel(entry)} · {entry.is_dir ? "—" : formatBytes(entry.size_bytes)}{formatModifiedAt(entry.modified_at) ? ` · ${formatModifiedAt(entry.modified_at)}` : ""}
                          </Typography>
                        </Box>
                      </Stack>
                      <Typography
                        variant="body2"
                        sx={{
                          color: "text.secondary",
                          display: { xs: "none", md: "block" }
                        }}>
                        {getFileTypeLabel(entry)}
                      </Typography>
                      <Typography
                        variant="body2"
                        sx={{
                          color: "text.secondary",
                          display: { xs: "none", md: "block" }
                        }}>
                        {entry.is_dir ? "—" : formatBytes(entry.size_bytes)}
                      </Typography>
                      <Typography
                        variant="body2"
                        sx={{
                          color: "text.secondary",
                          display: { xs: "none", md: "block" }
                        }}>
                        {formatModifiedAt(entry.modified_at) || "—"}
                      </Typography>
                      <Stack
                        direction="row"
                        spacing={0.5}
                        sx={{
                          justifyContent: { xs: "flex-start", md: "flex-end" },
                          gridColumn: { xs: "2 / span 1", md: "auto" },
                          flexWrap: "wrap",
                          rowGap: 0.5
                        }}>
                        {!entry.is_dir && (
                          <Tooltip title="Download fil">
                            <span>
                              <Button size="small" startIcon={<DownloadIcon />} variant="contained" disabled={!canControl || !!fileDownloadingPath || fileOperationBusy} onClick={(event) => { event.stopPropagation(); onRequestFileDownload(entry); }} sx={{ minWidth: 0 }}>
                                {busyThis ? <CircularProgress size={16} color="inherit" /> : "Hent"}
                              </Button>
                            </span>
                          </Tooltip>
                        )}
                        <Tooltip title="Omdøb">
                          <span>
                            <Button size="small" variant="outlined" color="inherit" disabled={!canControl || fileOperationBusy || fileBrowserLoading} onClick={(event) => { event.stopPropagation(); startInlineRename(entry); }} sx={{ minWidth: 34, px: 0.8 }}>
                              <DriveFileRenameOutlineIcon fontSize="small" />
                            </Button>
                          </span>
                        </Tooltip>
                        <Tooltip title="Slet permanent">
                          <span>
                            <Button size="small" variant="outlined" color="error" disabled={!canControl || fileOperationBusy || fileBrowserLoading} onClick={(event) => { event.stopPropagation(); onRequestDeleteEntry(entry); }} sx={{ minWidth: 34, px: 0.8 }}>
                              <DeleteOutlinedIcon fontSize="small" />
                            </Button>
                          </span>
                        </Tooltip>
                      </Stack>
                    </Box>
                  );
                })}
              </Stack>
            )}
          </Box>
        </Box>
      </Box>
      <Dialog
        open={uploadConflictDialogOpen}
        onClose={() => !transferUploading && setUploadConflictDialogOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>Gennemgå upload</DialogTitle>
        <DialogContent dividers>
          <Typography
            variant="body2"
            sx={{
              color: "text.secondary",
              mb: 1.5
            }}>
            Gennemgå filerne før upload.
          </Typography>
          <Stack spacing={1}>
            {Array.from(transferFiles || []).map((file, index) => {
              const key = getUploadFileKey(file);
              const exists = existingEntryNames.has(String(file?.name || ""));
              const strategy = uploadConflictStrategies[key] || "keep_both";
              return (
                <Box
                  key={`${key}-${index}`}
                  sx={{
                    display: "grid",
                    gridTemplateColumns: { xs: "1fr", sm: "minmax(0, 1fr) 150px 180px" },
                    gap: 1,
                    alignItems: "center",
                    p: 1,
                    borderRadius: 2,
                    border: exists ? "1px solid rgba(251,191,36,0.32)" : "1px solid rgba(148,163,184,0.14)",
                    bgcolor: exists ? "rgba(251,191,36,0.08)" : "rgba(15,23,42,0.36)",
                  }}
                >
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="body2" sx={{ fontWeight: 850, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={file.name}>
                      {file.name}
                    </Typography>
                    <Typography variant="caption" sx={{
                      color: "text.secondary"
                    }}>
                      {formatBytes(file.size)}
                    </Typography>
                  </Box>
                  <Chip
                    size="small"
                    label={exists ? "Findes allerede" : "Ny fil"}
                    sx={compactDarkChipSx(exists ? "warning" : "success", { justifySelf: { xs: "flex-start", sm: "end" } })}
                  />
                  {exists ? (
                    <Select
                      size="small"
                      value={strategy}
                      disabled={transferUploading}
                      onChange={(event) => setUploadConflictStrategy(file, event.target.value)}
                      sx={{ minWidth: 170 }}
                    >
                      <MenuItem value="keep_both">Behold begge</MenuItem>
                      <MenuItem value="skip">Spring over</MenuItem>
                    </Select>
                  ) : (
                    <Typography
                      variant="caption"
                      sx={{
                        color: "text.secondary",
                        justifySelf: { xs: "flex-start", sm: "end" }
                      }}>
                      Uploades
                    </Typography>
                  )}
                </Box>
              );
            })}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button
            color="inherit"
            disabled={transferUploading}
            onClick={() => setUploadConflictDialogOpen(false)}
          >
            Annuller
          </Button>
          <Button
            variant="contained"
            disabled={transferUploading}
            onClick={confirmUploadWithConflictStrategies}
          >
            Bekræft valg
          </Button>
        </DialogActions>
      </Dialog>
      <Menu
        open={!!emptyContextMenu}
        onClose={closeContextMenu}
        anchorReference="anchorPosition"
        anchorPosition={emptyContextMenu ? { top: emptyContextMenu.mouseY, left: emptyContextMenu.mouseX } : undefined}
      >
        <MenuItem onClick={() => { closeContextMenu(); onRequestCreateFolder?.(); }} disabled={!canControl || fileBrowserLoading || fileOperationBusy}>
          <ListItemIcon><CreateNewFolderIcon fontSize="small" /></ListItemIcon>
          <ListItemText>Ny mappe</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => { closeContextMenu(); fileInputRef.current?.click?.(); }} disabled={!canControl || transferUploading}>
          <ListItemIcon><UploadFileIcon fontSize="small" /></ListItemIcon>
          <ListItemText>Upload hertil</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => { closeContextMenu(); onRequestFileList(fileBrowserPath || ""); }} disabled={!canControl || fileBrowserLoading}>
          <ListItemIcon><RefreshIcon fontSize="small" /></ListItemIcon>
          <ListItemText>Opdater</ListItemText>
        </MenuItem>
      </Menu>
      <Menu
        open={!!contextMenu}
        onClose={closeContextMenu}
        anchorReference="anchorPosition"
        anchorPosition={contextMenu ? { top: contextMenu.mouseY, left: contextMenu.mouseX } : undefined}
      >
        {activeContextEntry?.is_dir && (
          <MenuItem onClick={() => handleContextAction("open")} disabled={!canControl || fileBrowserLoading || fileOperationBusy}>
            <ListItemIcon><KeyboardReturnIcon fontSize="small" /></ListItemIcon>
            <ListItemText>Åbn mappe</ListItemText>
          </MenuItem>
        )}
        {!activeContextEntry?.is_dir && (
          <MenuItem onClick={() => handleContextAction("download")} disabled={!canControl || !!fileDownloadingPath || fileOperationBusy}>
            <ListItemIcon><DownloadIcon fontSize="small" /></ListItemIcon>
            <ListItemText>Download</ListItemText>
          </MenuItem>
        )}
        <MenuItem onClick={() => handleContextAction("rename")} disabled={!canControl || fileBrowserLoading || fileOperationBusy}>
          <ListItemIcon><DriveFileRenameOutlineIcon fontSize="small" /></ListItemIcon>
          <ListItemText>Omdøb</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => handleContextAction("delete")} disabled={!canControl || fileBrowserLoading || fileOperationBusy} sx={{ color: "error.main" }}>
          <ListItemIcon><DeleteOutlinedIcon fontSize="small" color="error" /></ListItemIcon>
          <ListItemText>Slet permanent</ListItemText>
        </MenuItem>
      </Menu>
    </Paper>
  );
}
