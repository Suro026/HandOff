import {
  Hash, FileCheck, Link2, Eye, KeyRound, Film, Activity, Server, HardDrive, DatabaseBackup, Gauge, Archive, Mail, Upload,
} from 'lucide-react';
import { BentoGrid, type BentoItem } from './ui/bento-grid';

const s = 18;
// Ordered so every row of the 3-column grid is filled: 2+1, 1+2, 1+1+1, 2+1, 1+2, then 1+1+1.
const items: BentoItem[] = [
  { title: 'Originals stay original', description: 'Files are stored byte for byte as uploaded. No compression, resizing, transcoding or watermark, for preview or download.', icon: <FileCheck size={s} aria-hidden="true" />, status: 'MVP', tags: ['Quality'], colSpan: 2, hasPersistentHover: true },
  { title: 'SHA-256 on every file', description: 'Recorded while the file uploads and shown to the client, so either side can check a download.', icon: <Hash size={s} aria-hidden="true" />, status: 'MVP', tags: ['Quality'] },

  { title: 'Uploads of any size', description: 'Streamed to disk in small chunks. A free-space reserve and a stall timeout protect the machine instead of a fixed size limit.', icon: <Upload size={s} aria-hidden="true" />, status: 'MVP', tags: ['Quality'] },
  { title: 'Private, revocable links', description: 'Unguessable links that stop working the moment you revoke them. Only a hash is stored.', icon: <Link2 size={s} aria-hidden="true" />, status: 'MVP', tags: ['Sharing'], colSpan: 2, hasPersistentHover: true },

  { title: 'Password, expiry, download limit', description: 'Add any of them to a link. A page view never counts as a download.', icon: <KeyRound size={s} aria-hidden="true" />, status: 'MVP', tags: ['Sharing'] },
  { title: 'View-only links', description: 'No download button. They discourage casual saving and cannot prevent copying, and the page says so.', icon: <Eye size={s} aria-hidden="true" />, status: 'MVP', tags: ['Sharing'] },
  { title: 'Activity log', description: 'See when a link was opened, previewed or downloaded.', icon: <Activity size={s} aria-hidden="true" />, status: 'MVP', tags: ['Control'] },

  { title: 'Previews in the browser', description: 'Images, MP4 and WebM video with seeking, audio, PDF and text, using the browser itself.', icon: <Film size={s} aria-hidden="true" />, status: 'MVP', tags: ['Client'], colSpan: 2 },
  { title: 'One-click desktop app', description: 'One Handoff.exe starts everything on Windows. The owner dashboard stays on your computer.', icon: <Server size={s} aria-hidden="true" />, status: 'MVP', tags: ['Self-hosted'] },

  { title: 'Your data on your disk', description: 'A database for records and plain files for the originals, in one folder.', icon: <HardDrive size={s} aria-hidden="true" />, status: 'MVP', tags: ['Self-hosted'] },
  { title: 'Backup, restore, verify', description: 'Commands for a consistent backup, a restore, and a re-check of every stored file.', icon: <DatabaseBackup size={s} aria-hidden="true" />, status: 'MVP', tags: ['Self-hosted'], colSpan: 2 },

  { title: 'Download all as ZIP', description: 'One archive of everything on a link, streamed without loading it into memory.', icon: <Archive size={s} aria-hidden="true" />, status: 'Planned' },
  { title: 'Resumable uploads', description: 'For uploading from another computer over a slow connection.', icon: <Gauge size={s} aria-hidden="true" />, status: 'Planned' },
  { title: 'Email notices', description: 'Optional, using an email server you provide.', icon: <Mail size={s} aria-hidden="true" />, status: 'Planned' },
];

export default function FeatureBento() {
  return <BentoGrid items={items} />;
}
