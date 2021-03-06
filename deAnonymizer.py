from gitProfileSet import *
from Classifier import *
from coderID import MyPrompt
from Classifier import *
from sklearn import metrics
class DeAnonymizer:

    def __init__(self, weapon):
        self.profileSet = weapon
        self.authors = self.profileSet.authors
        self.model = None
        self.trainedNames = None           

    def attack(self, gps):
        """returns an NxK martrix with N=number of functions in gps, K=number of authors in self.authors"""
        """each index is the predicted probability that the author wrote the function"""

        targetFeatures = gps.counts
        targetTargets = gps.target
        targetNames = gps.terms

        from collections import Counter

        trainedFeatures = self.profileSet.counts
        trainedTargets = self.profileSet.target
        trainedNames = self.profileSet.terms

        candidateSet = set(trainedTargets)

        trainedCounts = Counter(trainedTargets)
        targetCounts = Counter(targetTargets)

        updatedCandidateSet = set()

        #only keep authors with at least ten samples in train and test
        for candidate in candidateSet:
            if trainedCounts[candidate] < 25 or targetCounts[candidate] < 10:
                print("Insufficient samples to test "+candidate)
            else:
                updatedCandidateSet.add(candidate)
        
        candidateSet = updatedCandidateSet


        print("unifying candidate sets")
        print(str(candidateSet))
        candidateIndeces = [i for i in range(len(targetTargets)) if targetTargets[i] in candidateSet]
        
        targetFeatures = targetFeatures[candidateIndeces,:]
        targetTargets = targetTargets[candidateIndeces]

        candidateIndeces = [i for i in range(len(trainedTargets)) if trainedTargets[i] in candidateSet]
        
        trainedFeatures = trainedFeatures[candidateIndeces,:]
        trainedTargets = trainedTargets[candidateIndeces]

        print("Trained:"+str(trainedCounts))
        print("Targets: "+str(targetCounts))

        print("unifying features")

        targetNameIndeces = dict()
        for index in range(len(targetNames)):
            targetNameIndeces[targetNames[index]] = index

        trainedNameIndeces = dict()
        for index in range(len(trainedNames)):
            trainedNameIndeces[trainedNames[index]] = index

        #take the intersection of available features between the target and source
        commonNames = listIntersection(targetNames, trainedNames)
        
        #filter to common features in trained
        trainedFeatures = filterFeatures(trainedFeatures, trainedNameIndeces, commonNames)
        

        featureSelect = False
        if featureSelect:
            #perform recursive feature elimination on whats left
            selectedFeatureIndeces = MyPrompt.reFeSe(Classifier().model, trainedFeatures, trainedTargets)
            selectedNames = [commonNames[i] for i in selectedFeatureIndeces]
            
            
            #redo these because they have changed
            trainedNameIndeces = dict()
            for index in range(len(selectedNames)):
                trainedNameIndeces[selectedNames[index]] = index


            #filter to only the selected Features
            trainedFeatures = filterFeatures(trainedFeatures, trainedNameIndeces, selectedNames)
            targetFeatures = filterFeatures(targetFeatures, targetNameIndeces, selectedNames)
        else:
            targetFeatures = filterFeatures(targetFeatures, targetNameIndeces, commonNames)

        print("training model")
        from sklearn.ensemble import RandomForestClassifier
        clf = RandomForestClassifier(criterion="entropy", n_estimators = 300, n_jobs=-1, class_weight = "balanced_subsample")
        clf.fit(trainedFeatures, trainedTargets)
        #predict the probabilities of the functions in the target repo
        print("predicting")
        return (clf.predict_proba(targetFeatures), clf.classes_, targetTargets, trainedCounts)

def filterFeatures(features, nameIndeces, commonNames):
    featureIndeces = [nameIndeces[name] for name in commonNames]
    return features[:,featureIndeces]

def listIntersection(fs1, fs2):
    return list(set(fs1).intersection(set(fs2)))

def testDeAnonymizer(deAnonymizer, target):
    """deAnonymizer: a DeAnonymizer with profile sets added
    target: a target profile set with authors we want to de-anonymize
    """
    
    pred_result, classes, groundTruth, trainingCounts = deAnonymizer.attack(target)

    predicted = []
    odds = []
    
    for predictedProbVector in pred_result:
        #find max and second place
        
        high = 0
        second = 0
        for index in range(len(predictedProbVector)):
            prob = predictedProbVector[index]
            if prob > high:
                second = high
                high = prob
                pred = classes[index]
            elif prob > second:
                second = prob

        confidence = high - second
        
        predicted.append(pred)
        #odds.append(confidence)

    report = dict()
    curves = dict()
    print("producing report")
    samples = range(len(predicted))
    print("Overall accuracy: "+str(len([i for i in samples if predicted[i]==groundTruth[i]])/len(samples)))
    for authorName in tqdm(classes):
        
        positives = [i for i in samples if predicted[i] == authorName]
        negatives = [i for i in samples if predicted[i] != authorName]

        occurances = [i for i in samples if groundTruth[i] == authorName]

        truePositives = [i for i in samples if predicted[i] == authorName and predicted[i] == groundTruth[i]]
        trueNegatives = [i for i in samples if predicted[i] != authorName and groundTruth[i] != authorName]
        falsePositives = [i for i in samples if predicted[i] == authorName and groundTruth[i] != authorName]
        falseNegatives = [i for i in samples if predicted[i] != authorName and groundTruth[i] == authorName]

        p = len(positives) #positives for the author
        
        
        oc = len(occurances) #occurances
        neg = (len(samples)-oc)
        prevelence = oc / len(samples)

        tp = len(truePositives)
        tn = len(trueNegatives)
        fp = len(falsePositives)
        fn = len(falseNegatives)

        recall = tp / oc
        prec = tp / p if p else 0
        fpr = fp / neg
        fnr = fn / (len(samples) - neg)
        spec = tn / neg
        acc = (tp+tn)/len(samples)
        
        faporate, trporate, thresholds = confidenceCurves([authorName]*len(groundTruth), groundTruth, [vec[list(classes).index(authorName)] for vec in pred_result])
        curves[authorName] = {"fpr":faporate, "tpr":trporate, authorName:{"AUC":metrics.auc(faporate, trporate), "support":oc}}
        curves[authorName]["targets"] = [1 if groundTruth[i] == predicted[i] else 0 for i in range(len(groundTruth))]
        curves[authorName]["predictions"] = [vec[list(classes).index(authorName)] for vec in pred_result]
        report[authorName] = {"prev":prevelence, "trained":trainingCounts[authorName], "occ":oc, "acc":acc, "spec":spec, "fpr":fpr, "fnr":fnr, "prec":prec, "recall":recall, "auc":metrics.auc(faporate, trporate)}
        
        

    print("Computing averages")
    averages = dict()
    median = dict()
    import statistics
    
    for stat in report[authorName]:
        stats = [report[authName][stat] for authName in report]
        averages[stat] = statistics.mean(stats)
        median[stat] = statistics.median(stats)
    
    report["avg"] = averages
    report["med"] = median
    
    return (report, curves)

def confidenceCurves(pred, true, confidence):
    def correct(i):
        if pred[i] == true[i]:
            return "correct"
        else:
            return "incorrect"

    correctNess = [correct(i) for i in range(len(pred))]
    return metrics.roc_curve(correctNess, confidence, pos_label="correct")

from collections import Counter
def cOcc(iter):
    return Counter(iter)