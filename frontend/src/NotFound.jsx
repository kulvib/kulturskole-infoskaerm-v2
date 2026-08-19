import React from "react";
import { Typography, Box, Button } from "@mui/material";
import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <Box
      sx={{
        minHeight: "60vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexDirection: "column",
      }}
    >
      <Typography variant="h4" sx={{ fontWeight: 700, mb: 2 }}>
        Siden blev ikke fundet
      </Typography>
      <Typography variant="subtitle1" sx={{ color: "#888", mb: 3 }}>
        Tjek adressen eller gå til forsiden.
      </Typography>
      <Button
        variant="contained"
        color="primary"
        component={Link}
        to="/"
        sx={{ fontWeight: 600, px: 4 }}
      >
        Gå til forsiden
      </Button>
    </Box>
  );
}
