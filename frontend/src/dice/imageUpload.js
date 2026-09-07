const SUPPORTED_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);

export const MAX_ORIGINAL_IMAGE_BYTES = 10 * 1024 * 1024;
export const COMMENT_IMAGE_MAX_EDGE = 1600;
export const COMMENT_THUMB_MAX_EDGE = 480;
export const AVATAR_IMAGE_MAX_EDGE = 256;

export function containedImageSize(width, height, maxEdge) {
  const scale = Math.min(1, maxEdge / Math.max(width, height));
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

function loadImage(file) {
  return new Promise((resolve, reject) => {
    const objectUrl = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(objectUrl);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error('That image could not be read.'));
    };
    image.src = objectUrl;
  });
}

function canvasBlob(canvas, quality) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob || blob.type !== 'image/webp') {
        reject(new Error('This browser cannot prepare the image for upload.'));
        return;
      }
      resolve(blob);
    }, 'image/webp', quality);
  });
}

function validateImage(file) {
  if (!SUPPORTED_IMAGE_TYPES.has(file.type)) {
    throw new Error('Use a JPEG, PNG, or WebP image.');
  }
  if (file.size > MAX_ORIGINAL_IMAGE_BYTES) {
    throw new Error('Image must be 10 MB or smaller.');
  }
}

export async function compactImageVariants(file, variants) {
  validateImage(file);
  const image = await loadImage(file);
  return Promise.all(variants.map(async ({ maxEdge, quality = 0.78 }) => {
    const dimensions = containedImageSize(
      image.naturalWidth || image.width,
      image.naturalHeight || image.height,
      maxEdge,
    );
    const canvas = document.createElement('canvas');
    canvas.width = dimensions.width;
    canvas.height = dimensions.height;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('This browser cannot prepare the image for upload.');
    context.drawImage(image, 0, 0, dimensions.width, dimensions.height);
    return canvasBlob(canvas, quality);
  }));
}

export async function compactImage(file, variant) {
  const [result] = await compactImageVariants(file, [variant]);
  return result;
}

export function imageVariantUrl(displayUrl, variant, download = false) {
  if (!displayUrl || !displayUrl.endsWith('/display.webp')) return displayUrl;
  const suffix = variant === 'original' ? '/original' : `/${variant}.webp`;
  const url = `${displayUrl.slice(0, -'/display.webp'.length)}${suffix}`;
  return download ? `${url}?download=dice-photo-original` : url;
}

export function uniqueImageFolder(userId) {
  const random = globalThis.crypto?.randomUUID?.()
    || `${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`;
  return `${userId}/${Date.now()}-${random}`;
}
