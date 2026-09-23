import { useBranding } from '../contexts/BrandingContext'

/**
 * What "submit for verification" actually does: share the item with the
 * people at this institution, via an examiner's review. Named for the
 * institution when the deployment is branded, since "Share with Vandalizer"
 * would name the software rather than the audience.
 */
export function shareLabel(b: { orgName: string; isCustomized: boolean }): string {
  return b.isCustomized ? `Share with ${b.orgName}` : 'Share to catalog'
}

export function useShareLabel(): string {
  return shareLabel(useBranding())
}

/** Inline text version for places that render children rather than take a string prop. */
export function ShareLabel() {
  return <>{useShareLabel()}</>
}
