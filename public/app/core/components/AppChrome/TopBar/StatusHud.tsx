import { css } from '@emotion/css';
import { useEffect, useState } from 'react';

import { type GrafanaTheme2 } from '@grafana/data';
import { t } from '@grafana/i18n';
import { getBackendSrv } from '@grafana/runtime';
import { useStyles2 } from '@grafana/ui';

type HealthStatus = 'ok' | 'error' | 'loading';

const POLL_INTERVAL_MS = 15_000;

export function StatusHud() {
  const styles = useStyles2(getStyles);
  const [status, setStatus] = useState<HealthStatus>('loading');

  useEffect(() => {
    let cancelled = false;

    const checkHealth = async () => {
      try {
        await getBackendSrv().get('/api/health', undefined, undefined, {
          showErrorAlert: false,
          showSuccessAlert: false,
        });
        if (!cancelled) {
          setStatus('ok');
        }
      } catch {
        if (!cancelled) {
          setStatus('error');
        }
      }
    };

    checkHealth();
    const intervalId = window.setInterval(checkHealth, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, []);

  if (status === 'loading') {
    return null;
  }

  const isOk = status === 'ok';
  const label = isOk ? t('navigation.status-hud.ok', 'OK') : t('navigation.status-hud.error', 'Error');

  return (
    <div
      className={styles.hud}
      data-testid="status-hud"
      data-status={status}
      role="status"
      aria-live="polite"
      aria-label={t('navigation.status-hud.aria-label', 'System status: {{status}}', { status: label })}
      title={t('navigation.status-hud.title', 'Grafana health status')}
    >
      <span className={isOk ? styles.dotOk : styles.dotError} aria-hidden />
      {isOk && <span className={styles.label}>{label}</span>}
    </div>
  );
}

const litDot = (color: string, glow: string) =>
  css({
    width: 10,
    height: 10,
    borderRadius: '50%',
    flexShrink: 0,
    background: `radial-gradient(circle at 35% 30%, #fff 0%, ${color} 45%, ${glow} 100%)`,
    boxShadow: `0 0 6px 1px ${glow}`,
  });

const getStyles = (theme: GrafanaTheme2) => ({
  hud: css({
    display: 'inline-flex',
    alignItems: 'center',
    gap: theme.spacing(0.75),
    padding: theme.spacing(0, 1),
    whiteSpace: 'nowrap',
    userSelect: 'none',
  }),
  dotOk: litDot(theme.colors.success.main, theme.colors.success.transparent),
  dotError: litDot(theme.colors.error.main, theme.colors.error.transparent),
  label: css({
    fontSize: theme.typography.bodySmall.fontSize,
    fontWeight: theme.typography.fontWeightMedium,
    color: theme.colors.text.secondary,
    lineHeight: 1,
  }),
});
