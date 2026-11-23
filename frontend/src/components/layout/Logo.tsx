import Image from "next/image";
import { LOGO_SRC } from "@/lib/brand";
import styles from "./Logo.module.css";

// The PNG has a white background and wide padding, so it sits in a rounded tile, zoomed in.
export function Logo({ size = 32 }: { size?: number }) {
  return (
    <span className={styles.tile} style={{ width: size, height: size }}>
      <Image src={LOGO_SRC} alt="" width={size} height={size} className={styles.mark} />
    </span>
  );
}
