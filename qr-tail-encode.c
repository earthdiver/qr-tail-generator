/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Module placement adapted from libqrencode:
 * Copyright (C) 2006-2014 Kentaro Fukuchi <kentaro@fukuchi.org>
 * Copyright (C) 2026 QR post-terminator generator contributors
 *
 * Extension to the pinned libqrencode encoder. Include its implementation to
 * reuse its private RS blocks and module placement without changing vendor/.
 */
#include "vendor/libqrencode/qrencode.c"
#include <limits.h>

/* stats: failing block (1-based, 0 on success), differences, limit,
 * minimum remaining correction capacity across all blocks.
 * Both inputs must have the same level; versions are minimum versions.
 */
QRcode *QRcode_encodeReplacement(QRinput *input, QRinput *replacement,
                               int mask, int stats[4])
{
    QRRawCode *actual = NULL, *target = NULL;
    QRcode *result = NULL;
    unsigned char *frame = NULL, *masked = NULL, *cell;
    FrameFiller filler;
    int version, width, i, j, differences, limit;

    memset(stats, 0, 4 * sizeof(int));
    stats[3] = INT_MAX;
    if(input->mqr || replacement->mqr || input->level != replacement->level ||
       mask < -1 || mask > 7) {
        errno = EINVAL;
        return NULL;
    }
    /* Encoding may enlarge either input, including across count-bit changes.
     * Re-encode at a shared version until both streams use the same layout. */
    for(;;) {
        actual = QRraw_new(input);
        target = QRraw_new(replacement);
        if(actual == NULL || target == NULL) goto cleanup;
        if(actual->version == target->version) break;
        version = actual->version > target->version ? actual->version : target->version;
        QRraw_free(actual);
        QRraw_free(target);
        actual = target = NULL;
        QRinput_setVersion(input, version);
        QRinput_setVersion(replacement, version);
    }
    for(i = 0; i < actual->blocks; i++) {
        differences = 0;
        for(j = 0; j < actual->rsblock[i].dataLength; j++) {
            differences += actual->rsblock[i].data[j] != target->rsblock[i].data[j];
        }
        limit = actual->rsblock[i].eccLength / 2;
        if(differences > limit) {
            stats[0] = i + 1;
            stats[1] = differences;
            stats[2] = limit;
            errno = EINVAL;
            goto cleanup;
        }
        if(limit - differences < stats[3]) stats[3] = limit - differences;
    }
    memcpy(actual->ecccode, target->ecccode, actual->eccLength);

    version = actual->version;
    width = QRspec_getWidth(version);
    frame = QRspec_newFrame(version);
    if(frame == NULL) goto cleanup;
    FrameFiller_set(&filler, width, frame, 0);
    for(i = 0; i < actual->dataLength + actual->eccLength; i++) {
        unsigned char code = QRraw_getCode(actual);
        for(j = 7; j >= 0; j--) {
            cell = FrameFiller_next(&filler);
            if(cell == NULL) goto cleanup;
            *cell = 0x02 | ((code >> j) & 1);
        }
    }
    for(i = 0; i < QRspec_getRemainder(version); i++) {
        cell = FrameFiller_next(&filler);
        if(cell == NULL) goto cleanup;
        *cell = 0x02;
    }
    masked = mask < 0 ? Mask_mask(width, frame, input->level)
                     : Mask_makeMask(width, frame, mask, input->level);
    if(masked == NULL) goto cleanup;
    result = QRcode_new(version, width, masked);
    if(result == NULL) free(masked);
cleanup:
    free(frame);
    QRraw_free(actual);
    QRraw_free(target);
    return result;
}
