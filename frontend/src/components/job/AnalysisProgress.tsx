interface AnalysisProgressProps {
  steps: string[];
  activeStep: number;
  isAnalyzing: boolean;
}

export function AnalysisProgress({ steps, activeStep, isAnalyzing }: AnalysisProgressProps) {
  if (!isAnalyzing) return null;
  return (
    <div className="progress-panel" aria-live="polite">
      {steps.map((step, index) => (
        <div key={step} className={index <= activeStep ? "active" : ""}>
          <span>{index + 1}</span>
          {step}
        </div>
      ))}
    </div>
  );
}
