import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogContentText from "@mui/material/DialogContentText";
import DialogTitle from "@mui/material/DialogTitle";
import Typography from "@mui/material/Typography";
import { formatSessionCountdown } from "./sessionPolicy";

export default function SessionTimeoutDialog({
  type,
  secondsRemaining,
  continuePending,
  continueError,
  onContinue,
  onLogout,
  onLoginAgain,
  onDismissAbsolute,
}) {
  const isIdle = type === "idle";
  const isAbsolute = type === "absolute";
  const countdown = formatSessionCountdown(secondsRemaining);

  return (
    <Dialog
      open={Boolean(type)}
      aria-labelledby="session-timeout-title"
      aria-describedby="session-timeout-description"
      maxWidth="xs"
      fullWidth
    >
      <DialogTitle id="session-timeout-title">
        {isIdle ? "Din session udløber snart" : "Du skal snart logge ind igen"}
      </DialogTitle>
      <DialogContent>
        <DialogContentText id="session-timeout-description" component="div">
          {isIdle ? (
            <>
              Du har været inaktiv. Af sikkerhedshensyn bliver du automatisk logget ud om:
            </>
          ) : (
            <>
              Den maksimale sessionstid på 6 timer er ved at være nået. Gem eventuelle ændringer. Du bliver automatisk logget ud om:
            </>
          )}
        </DialogContentText>

        <Typography
          component="p"
          variant="h4"
          sx={{ mt: 2, mb: 1, fontWeight: 800, fontVariantNumeric: "tabular-nums" }}
          aria-live="polite"
        >
          {countdown}
        </Typography>

        {isIdle && (
          <DialogContentText component="p">
            Vælg <strong>Fortsæt session</strong> for at kontrollere sessionen hos serveren og fortsætte arbejdet.
          </DialogContentText>
        )}

        {isAbsolute && (
          <DialogContentText component="p">
            Aktivitet kan ikke forlænge den absolutte session. Du kan logge ind igen nu eller fortsætte frem til udløbet.
          </DialogContentText>
        )}

        {continueError && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {continueError}
          </Alert>
        )}
      </DialogContent>

      <DialogActions sx={{ px: 3, pb: 2.5, gap: 1, flexWrap: "wrap" }}>
        {isIdle && (
          <>
            <Button onClick={onLogout} color="error" disabled={continuePending}>
              Log ud
            </Button>
            <Button
              onClick={onContinue}
              variant="contained"
              disabled={continuePending}
              loading={continuePending}
              loadingPosition="start"
              autoFocus
            >
              Fortsæt session
            </Button>
          </>
        )}

        {isAbsolute && (
          <>
            <Button onClick={onDismissAbsolute}>
              Fortsæt til udløb
            </Button>
            <Button onClick={onLoginAgain} variant="contained" autoFocus>
              Log ind igen
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}
