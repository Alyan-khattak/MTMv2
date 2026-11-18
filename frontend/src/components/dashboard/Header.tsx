import styles from "./Header.module.css";

export default function Header({ title, running }: { title: string; running: boolean }) {
  return (
    <header className={styles.header}>
      <h1 className={styles.title}>{title}</h1>
      <div className={styles.workspacePill}>{running ? "Running..." : "Idle"}</div>
    </header>
  );
}
