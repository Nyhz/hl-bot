import { describe, it, expect } from "vitest";
import { buildLaunchBody } from "../control";

describe("buildLaunchBody", () => {
  it("solo envía capital y pérdida máxima (el perfil vive en el servidor)", () => {
    const body = buildLaunchBody({ capital: 60, maxLoss: 10 });
    expect(body).toEqual({ capital: 60, max_loss: 10 });
  });
});
