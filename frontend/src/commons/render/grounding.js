// Legacy cutouts are registered at their nearest contact. Sort their whole
// body at the middle of the measured support span until authored pieces exist.
export function supportDepthOffset(metadata) {
  const { supportPointsPx, sourceSizePx, anchor, width, height } = metadata;
  if (!supportPointsPx?.length) return metadata.depthOffset || 0;
  const scaleY = height ? height / sourceSizePx[1] : width / sourceSizePx[0];
  const depths = supportPointsPx.map(([, y]) => y);
  const centerY = (Math.min(...depths) + Math.max(...depths)) / 2;
  return (centerY - anchor[1] * sourceSizePx[1]) * scaleY + (metadata.depthOffset || 0);
}
