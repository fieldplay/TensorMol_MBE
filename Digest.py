#
# An Embedding gives some chemical description of a molecular
# Environment around a point
#
# A Digester samples a molecule using an embedding.
# Because the embedding is evaluated so much, it's written in C. please refer to /C_API/setup.py
#
# The Default is Coulomb, but this is also the gen. interface
# The embedding does not provide labels.
#

from Mol import *
from Util import *
import numpy,os,sys,pickle,re
if (HAS_EMB): 
	import MolEmb

class Digester:
	def __init__(self, eles_, name_="SensoryBasis", OType_="", SamplingType_="", BlurRadius_ = 0.05 ):
		
		 # In Atomic units at 300K
		# These are the key variables which determine the type of digestion.
		self.name = name_ # Embedding type.
		self.OType = "SmoothP" # Output Type: HardP, SmoothP, StoP, Force, Energy etc. See Emb() for options.
		if (OType_ != ""):
			self.OType=OType_
		self.SamplingType = "Smooth" # No hard cutoff of sampled points.
		if (SamplingType_ != ""):
			self.SamplingType = SamplingType_

		self.NTrainSamples=1 # Samples per atom. Should be made a parameter.
		if (self.OType == "SmoothP"):
			self.NTrainSamples=1 #Smoothprobability only needs one sample because it fits the go-probability and pgaussians-center.

		self.eles = eles_ # Consistent list of atoms in the order they are treated.
		self.neles = len(eles_) # Consistent list of atoms in the order they are treated.
		self.TrainSampDistance=2.0 #how far in Angs to sample on average.
		

	
		self.ngrid = 20 #this is a shitty parameter if we go with anything other than RDF and should be replaced.
		self.nsym = self.neles+(self.neles+1)*self.neles  # channel of sym functions
		self.npgaussian = self.neles # channel of PGaussian
		# Instead self.emb should know it's return shape or it should be testable.
		self.lshape=None # shape of label array.
		self.eles = eles_ # Consistent list of atoms in the order they are treated.
		self.neles = len(eles_) # Consistent list of atoms in the order they are treated.
		self.BlurRadius = BlurRadius_ # Stdev of gaussian used as prob of atom
		self.SensRadius=6.0 # Distance which is used for input.

		self.eshape=None  #shape of an embedded case
		self.lshape=None  #shape of the labels of an embedded case.
		
		self.Print()
		return

	def Print(self):
		print "-------------------- "
		print "Digester Information "
		print "self.name", self.name
		print "self.OType", self.OType
		print "self.SamplingType", self.SamplingType
		print "self.NTrainSamples", self.NTrainSamples
		print "self.TrainSampDistance", self.TrainSampDistance
		print "-------------------- "
		return

	def MakeSamples_v2(self,point):    # with sampling function f(x)=M/(x+1)^2+N; f(0)=maxdisp,f(maxdisp)=0; when maxdisp =5.0, 38 % lie in (0, 0.1)
		disps = samplingfunc_v2(self.TrainSampDistance * np.random.random(self.NTrainSamples), self.TrainSampDistance)
		theta  = np.random.random(self.NTrainSamples)* math.pi
		phi = np.random.random(self.NTrainSamples)* math.pi * 2
		grids  = np.zeros((self.NTrainSamples,3),dtype=np.float32)
		grids[:,0] = disps*np.cos(theta)
		grids[:,1] = disps*np.sin(theta)*np.cos(phi)
		grids[:,2] = disps*np.sin(theta)*np.sin(phi)
		return grids + point

	def Blurs(self, diffs):
		dists=np.array(map(np.linalg.norm,diffs))
		return np.exp(dists*dists/(-1.0*self.BlurRadius*self.BlurRadius))/(np.power(2.0*Pi*self.BlurRadius*self.BlurRadius,3.0/2.0))
     
	def HardCut(self, diffs, cutoff=0.05):
		# 0, 1 output
		dists=np.array(map(np.linalg.norm,diffs))
		labels = np.clip(-(dists - cutoff), 0, (-(dists - cutoff)).max())
		labels[np.where(labels > 0)]=1
		return labels

#
#  Embedding functions, called by batch digests. Use outside of Digester() is discouraged.
#  Instead call a batch digest routine.
#

	def Emb(self, mol_, at_, xyz_, MakeOutputs=True):
		Ins=(self.EmbF(mol_))(mol_.coords, xyz_, mol_.atoms , self.eles ,  self.SensRadius, self.ngrid, at_, 0.0)
		Outs=None
		if (MakeOutputs):
			if (self.OType=="HardP"):
				Outs = self.HardCut(xyz_-coords_[at_])
			elif (self.OType=="SmoothP"):
				Outs = mol_.FitGoProb(at_)
			elif (self.OType=="StoP"):
				ens_ = mol_.EnergiesOfAtomMoves(xyz_,at_)
				if (ens_==None):
					raise Exception("Empty energies...")
				E0=np.min(ens_)
				Es=ens_-E0
				Boltz=np.exp(-1.0*Es/KAYBEETEE)
				rnds = np.random.rand(len(xyz_))
				Outs = np.array([1 if rnds[i]<Boltz[i] else 0 for i in range(len(ens_))])
			elif (self.OType=="Energy"):
				ens_ = mol_.EnergiesOfAtomMoves(xyz_,at_)
				if (ens_==None):
					raise Exception("Empty energies...")
				E0=np.min(ens_)
				Es=ens_-E0
				Outs = Es
			elif (self.OType=="Force"):
				ens_ = mol_.ForcesAfterAtomMove(xyz_,at_)
				if (ens_==None):
					raise Exception("Empty energies...")
			elif (self.OType=="GoForce_old_version"): # python version is fine for here
                                ens_ = mol_.SoftCutGoForceOneAtom(at_)
				Outs = ens_.reshape((1,-1))  #just for the outs[0] in TrainDigest 
                                if (ens_==None):
                                        raise Exception("Empty energies...")
			else:
				raise Exception("Unknown Digester Output Type.")
			return Ins,Outs
		else:
			return Ins

	def EmbF(self,mol_=None):
		if (self.name=="Coulomb"):
			return MolEmb.Make_CM
		elif (self.name=="RDF"):
			return MolEmb.Make_RDF
		elif (self.name=="SensoryBasis"):
			return mol_.OverlapEmbeddings
		elif (self.name=="SymFunc"):
			return self.make_sym
		elif (self.name=="PGaussian"):
			return self.make_pgaussian
		else:
			raise Exception("Unknown Embedding Function.")


#  Various types of Batch Digests.
#

	def TrainDigest(self, mol_, ele_):
		""" 
			Returns list of inputs and output gaussians.
			Uses self.Emb() uses Mol to get the Desired output type (Energy,Force,Probability etc.)
		"""
		t1 = time.time()
		if (self.eshape==None or self.lshape==None):
			tinps, touts = self.Emb(mol_,0,np.array([[0.0,0.0,0.0]]))
			self.eshape = list(tinps[0].shape)
			self.lshape = list(touts[0].shape)
			print "Assigned Digester shapes: ",self.eshape,self.lshape
		
		ncase = mol_.NumOfAtomsE(ele_)*self.NTrainSamples
		ins = np.zeros(shape=tuple([ncase]+list(self.eshape)),dtype=np.float32)
		outs=np.zeros(shape=tuple([ncase]+list(self.lshape)),dtype=np.float32)
		casep=0
		for i in range(len(mol_.atoms)):
			if (mol_.atoms[i]==ele_):

				if (self.OType == "SmoothP"):
					inputs, outputs = self.Emb(mol_,i,[mol_.coords[i]]) # will deal with getting energies if it's needed.
				elif(self.SamplingType=="Smooth"): #If Smooth is now a property of the Digester: OType SmoothP
					samps=PointsNear(mol_.coords[i], self.NTrainSamples, self.TrainSampDistance)
					inputs, outputs = self.Emb(mol_,i,samps) # will deal with getting energies if it's needed.
				elif(self.OType=="GoForce_old_version"):
					inputs, outputs = self.Emb(mol_,i, mol_.coords[i].reshape((1,-1)))
				else:
					samps=self.MakeSamples_v2(mol_.coords[i])
					inputs, outputs = self.Emb(mol_,i,samps)
# Here we should write a short routine to debug/print the inputs and outputs.
#				print "Smooth",outputs
#print i, mol_.atoms, mol_.coords,mol_.coords[i],"Samples:",samps,"inputs ", inputs, "Outputs",outputs, "Distances",np.array(map(np.linalg.norm,samps-mol_.coords[i]))
				ins[casep:casep+self.NTrainSamples] = np.array(inputs)
				outs[casep:casep+self.NTrainSamples] = outputs
				casep += self.NTrainSamples
		return ins,outs


	def SampleDigestWPyscf(self, mol_, ele_,uniform=False):
		''' Runs PySCF calculations for each sample without generating embeddings and probabilities '''
		for i in range(len(mol_.atoms)):
			if (mol_.atoms[i]==ele_):
				samps=None
				if (not uniform):
					samps=self.MakeSamples(mol_.coords[i])
				else: 
					samps=MakeUniform(mol_.coords[i],4.0,20)
				energies=mol_.RunPySCFWithCoords(samps,i)

	def UniformDigest(self, mol_, at_, mxstep, num):
		""" Returns list of inputs sampled on a uniform cubic grid around at """
		ncase = num*num*num
		samps=MakeUniform(mol_.coords[at_],mxstep,num)
		if (self.name=="SymFunc"):
			inputs = self.Emb(self, mol_, at_, samps, None, False) #(self.EmbF())(mol_.coords, samps, mol_.atoms, self.eles ,  self.SensRadius, self.ngrid, at_, 0.0)
			inputs = np.asarray(inputs)
		else:
			inputs = self.Emb(self, mol_, at_, samps, None, False)
			inputs = np.assrray(inputs[0])
		return samps, inputs

	def emb_vary_coords(self, coords, xyz, atoms, eles, Radius, ngrid, vary_at, tar_at):
		return  MolEmb.Make_CM_vary_coords(coords, xyz, atoms, eles, Radius, ngrid, vary_at, tar_at)




	def make_sym(self, coords_, xyz_, ats_,  eles , SensRadius, ngrid, at_, dummy):    #coords_, xyz_, ats_, self.eles ,  self.SensRadius, self.ngrid, at_, 0.0
		zeta=[]
		eta1=[]
		eta2=[]
		Rs=[]
		for i in range (0, ngrid):
			zeta.append(1.5**i)    # set some value for zeta, eta, Rs
			eta1.append(0.008*(2**i))
			eta2.append(0.002*(2**i))
			Rs.append(i*SensRadius/float(ngrid))
		SYM =  MolEmb.Make_Sym(coords_, xyz_, ats_, eles, at_, SensRadius, zeta, eta1, eta2, Rs)    
		SYM = numpy.asarray(SYM[0], dtype=np.float32)
		SYM = SYM.reshape((SYM.shape[0]/self.nsym, self.nsym,  SYM.shape[1] *  SYM.shape[2]))
		return SYM

	def make_pgaussian (self, coords_, xyz_, ats_, eles_, SensRadius, ngrid, at_, dummy):
		eta = []
		eta_max = 12  # hard code
		eta_min = 0.5 #	hard code
		for i in range (0, ngrid):
			tmp=math.log(eta_max/eta_min)/(ngrid-1)*i
			eta.append(pow(math.e, tmp)*eta_min)
		PGaussian = MolEmb.Make_PGaussian(coords_, xyz_, ats_, eles_, at_, SensRadius, eta)
		PGaussian = numpy.asarray(PGaussian[0], dtype=np.float32)
                PGaussian = PGaussian.reshape((PGaussian.shape[0]/self.npgaussian, self.npgaussian,  PGaussian.shape[1] *  PGaussian.shape[2]))
                return PGaussian
