/*
 * smartcard_channel_probe.c
 *
 * Phase 1 harness: exercises the same WinPR PC/SC API that FreeRDP's
 * MS-RDPESC "smartcard" redirection channel uses on the client side.
 *
 * This proves that an app embedding libfreerdp3 (instead of shelling out to
 * xfreerdp) can enumerate and drive the local smartcard through pcscd, which
 * is what gets proxied to the remote Windows session host.
 *
 * Build:
 *   env PKG_CONFIG_PATH=/opt/freerdp3/usr/lib/x86_64-linux-gnu/pkgconfig \
 *       cc -o smartcard_channel_probe smartcard_channel_probe.c \
 *       $(pkg-config --cflags --libs freerdp3)
 *
 * Run:
 *   LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu ./smartcard_channel_probe
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <winpr/collections.h>
#include <winpr/smartcard.h>

static void report_error(const char* what, LONG rv)
{
	fprintf(stderr, "[FAIL] %s: 0x%08lx\n", what, (unsigned long)rv);
}

int main(void)
{
	LONG rv;
	SCARDCONTEXT ctx = 0;
	DWORD nReaders = 0;
	LPSTR readers = NULL;
	LPSTR it = NULL;

	/* SCardEstablishContext: exactly what the scard channel calls on connect */
	rv = SCardEstablishContext(SCARD_SCOPE_SYSTEM, NULL, NULL, &ctx);
	if (rv != SCARD_S_SUCCESS) {
		report_error("SCardEstablishContext", rv);
		return EXIT_FAILURE;
	}
	printf("[OK] SCardEstablishContext\n");

	/* SCardListReadersA: what the channel uses to enumerate readers */
	rv = SCardListReadersA(ctx, NULL, NULL, &nReaders);
	if (rv != SCARD_S_SUCCESS || nReaders == 0) {
		report_error("SCardListReadersA (sizing)", rv);
		SCardReleaseContext(ctx);
		return EXIT_FAILURE;
	}
	readers = (LPSTR)calloc(nReaders, sizeof(char));
	if (!readers) {
		fprintf(stderr, "[FAIL] calloc\n");
		SCardReleaseContext(ctx);
		return EXIT_FAILURE;
	}
	rv = SCardListReadersA(ctx, NULL, readers, &nReaders);
	if (rv != SCARD_S_SUCCESS) {
		report_error("SCardListReadersA", rv);
		free(readers);
		SCardReleaseContext(ctx);
		return EXIT_FAILURE;
	}

	printf("[OK] SCardListReadersA:\n");
	it = readers;
	while (*it) {
		SCARDHANDLE hCard = 0;
		DWORD dwActiveProtocol = 0;
		printf("    - %s\n", it);
		/* Connect to reader (shared, any protocol) */
		rv = SCardConnectA(ctx, it, SCARD_SHARE_SHARED,
		                   SCARD_PROTOCOL_T0 | SCARD_PROTOCOL_T1,
		                   &hCard, &dwActiveProtocol);
		if (rv == SCARD_S_SUCCESS) {
			printf("      connected (protocol %lu)\n",
			       (unsigned long)dwActiveProtocol);
			SCardDisconnect(hCard, SCARD_UNPOWER_CARD);
		} else {
			printf("      (no card / cannot connect: 0x%08lx)\n",
			       (unsigned long)rv);
		}
		it += strlen(it) + 1;
	}
	free(readers);
	SCardReleaseContext(ctx);
	printf("[OK] SCardReleaseContext\n");

	printf("\nRESULT: PASS\n");
	return EXIT_SUCCESS;
}